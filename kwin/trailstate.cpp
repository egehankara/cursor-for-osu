// Trail behaviour adapted from osu!lazer (Copyright (c) ppy Pty Ltd, MIT).

#include "trailstate.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>

#include <algorithm>
#include <cmath>
#include <utility>

namespace OsuCursor
{
namespace
{
constexpr int MaxImageSide = 4096;
constexpr int MaxStateBytes = 64 * 1024;
constexpr int MaxParts = 2048;
constexpr qreal StampInterval = 1000.0 / 60;
}

QRectF TrailConfig::stamp(QPointF pos) const
{
    if (centred) {
        pos -= QPointF(size.width() / 2, size.height() / 2);
    }
    return {pos, size};
}

std::optional<TrailConfig> readTrail(const QString &directory, bool &invalid)
{
    const QDir dir(directory);
    const QString statePath = dir.filePath(QStringLiteral("state.json"));
    const QFileInfo stateInfo(statePath);
    QFile state(statePath);
    invalid = false;
    if (!state.exists()) {
        return std::nullopt;
    }
    invalid = true;
    if (!stateInfo.isFile() || stateInfo.isSymLink() || !state.open(QIODevice::ReadOnly)
        || state.size() > MaxStateBytes) {
        return std::nullopt;
    }
    const auto root = QJsonDocument::fromJson(state.read(MaxStateBytes + 1)).object();
    if (root.value("version").toInt() != 1) {
        return std::nullopt;
    }
    if (root.value("trail_enabled") == QJsonValue(false) || root.value("trail").isNull()) {
        invalid = false;
        return std::nullopt;
    }

    static const QRegularExpression ThemePattern(QStringLiteral("^osu-cursor-plasma-[0-9a-f]{12}$"));
    static const QRegularExpression TexturePattern(QStringLiteral("^trail-[0-9a-f]{12}\\.rgba$"));
    const auto trail = root.value("trail").toObject();
    const QString theme = root.value("theme").toString();
    const QString filename = trail.value("file").toString();
    const int width = trail.value("width").toInt();
    const int height = trail.value("height").toInt();
    const QSizeF size(trail.value("display_width").toDouble(), trail.value("display_height").toDouble());
    const qreal interval = trail.value("interval").toDouble();
    if (!ThemePattern.match(theme).hasMatch() || !TexturePattern.match(filename).hasMatch()
        || width <= 0 || height <= 0 || width > MaxImageSide || height > MaxImageSide
        || size.isEmpty() || size.width() > MaxImageSide || size.height() > MaxImageSide
        || interval <= 0 || !trail.value("disjoint").isBool() || !trail.value("centre").isBool()) {
        return std::nullopt;
    }

    const auto cursor = root.value("skin_cursor");
    QSizeF cursorSize;
    QPointF hotspot;
    if (!cursor.isNull()) {
        const auto shape = cursor.toObject();
        cursorSize = QSizeF(shape.value("width").toInt(), shape.value("height").toInt());
        hotspot = QPointF(shape.value("hot_x").toInt(-1), shape.value("hot_y").toInt(-1));
        if (cursorSize.isEmpty() || cursorSize.width() > MaxImageSide || cursorSize.height() > MaxImageSide
            || hotspot.x() < 0 || hotspot.y() < 0
            || hotspot.x() >= cursorSize.width() || hotspot.y() >= cursorSize.height()) {
            return std::nullopt;
        }
    }

    const QString texturePath = dir.filePath(filename);
    const QFileInfo info(texturePath);
    const qint64 length = qint64(width) * height * 4;
    QFile file(texturePath);
    if (!info.isFile() || info.isSymLink() || !file.open(QIODevice::ReadOnly) || file.size() != length) {
        return std::nullopt;
    }
    const QByteArray pixels = file.read(length);
    if (pixels.size() != length) {
        return std::nullopt;
    }
    const QImage image(reinterpret_cast<const uchar *>(pixels.constData()), width, height,
                       width * 4, QImage::Format_RGBA8888_Premultiplied);
    auto texture = image.copy();
    if (texture.isNull()) {
        return std::nullopt;
    }
    invalid = false;
    return TrailConfig{theme, std::move(texture), size, std::max(interval, 0.5),
                       trail.value("disjoint").toBool(), trail.value("centre").toBool(), cursorSize, hotspot};
}

void TrailParts::add(QPointF pos, qreal now)
{
    if (m_parts.size() == MaxParts) {
        m_parts.pop_front();
    }
    m_parts.push_back({pos, now});
}

void TrailParts::move(const TrailConfig &config, QPointF pos, qreal now)
{
    if (config.disjoint) {
        m_current = pos;
        return;
    }
    if (!m_anchor) {
        m_anchor = Part{pos, now};
        return;
    }
    const Part from = *m_anchor;
    const QPointF delta = pos - from.pos;
    const qreal distance = std::hypot(delta.x(), delta.y());
    const qreal end = distance - config.interval;
    // Keep bounded work even after a very large pointer warp.
    const qreal start = std::max(config.interval, end - MaxParts * config.interval);
    for (qreal d = start; d < end; d += config.interval) {
        const QPointF step = from.pos + delta * (d / distance);
        add(step, now);
        m_anchor = Part{step, now};
    }
}

void TrailParts::stamp(const TrailConfig &config, qreal now)
{
    if (!config.disjoint || !m_current) {
        return;
    }
    const QPointF to = *m_current;
    if (!m_stamped) {
        add(to, now);
        m_stamped = to;
        m_lastStamp = now;
        m_nextStamp = now + StampInterval;
        m_lastMotion = now;
        return;
    }
    if (now < m_nextStamp) {
        return;
    }
    // Frames can come less often than 60 times a second. The parts missed since the
    // last one go along the path, already aged. The trail clock stops while the cursor
    // rests, so after a rest only the time actually moved is filled in.
    const QPointF from = *m_stamped;
    const qreal elapsed = now - m_lastStamp;
    const int missing = qRound(elapsed / StampInterval) - 1;
    const int longest = int(std::ceil(config.fade() / StampInterval)) - 1;
    for (int k = std::min(missing, longest); k >= 1; --k) {
        const qreal age = k * StampInterval;
        add(from + (to - from) * (1 - age / elapsed), now - age);
    }
    add(to, now);
    if (from != to) {
        m_lastMotion = now;
    }
    m_lastStamp = now;
    // Staying on a 60 Hz grid keeps the rate exact however frames fall around it.
    m_nextStamp = now + StampInterval - std::fmod(now - m_nextStamp, StampInterval);
    m_stamped = to;
}

bool TrailParts::settled(const TrailConfig &config, qreal now) const
{
    return config.disjoint && m_current && now - m_lastMotion > config.fade() + StampInterval;
}

void TrailParts::expire(qreal now, qreal fade)
{
    while (!m_parts.empty() && now - m_parts.front().born >= fade) {
        m_parts.pop_front();
    }
}

void TrailParts::stopGrowing()
{
    m_anchor.reset();
    m_current.reset();
    m_stamped.reset();
}

void TrailParts::clear()
{
    m_parts.clear();
    stopGrowing();
}
}
