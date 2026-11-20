#pragma once

#include <QImage>
#include <QPointF>
#include <QRectF>
#include <QString>

#include <deque>
#include <optional>

namespace OsuCursor
{
struct TrailConfig {
    QString theme;
    QImage texture;
    QSizeF size;
    qreal interval;
    bool disjoint;
    bool centred;
    QSizeF cursorSize;
    QPointF hotspot;

    qreal fade() const { return disjoint ? 150.0 : 500.0; }
    QRectF stamp(QPointF pos) const;
};

// An absent or disabled trail is normal. Invalid data is reported to the app.
std::optional<TrailConfig> readTrail(const QString &directory, bool &invalid);

struct Part {
    QPointF pos;
    qreal born;
};

// Times are in trail time, a clock that only runs while the trail changes.
class TrailParts
{
public:
    // Continuous trails line parts up along the movement. Disjoint ones only note
    // where the cursor is, stamp() drops their parts.
    void move(const TrailConfig &config, QPointF pos, qreal now);
    // Disjoint trails: a part where the cursor is, 60 times a second, also while it
    // rests, as osu!lazer's LegacyCursorTrail does.
    void stamp(const TrailConfig &config, qreal now);
    // A disjoint trail under a resting cursor keeps a stack of parts that no longer
    // changes, so the clock can stop and the screen go idle.
    bool settled(const TrailConfig &config, qreal now) const;
    void expire(qreal now, qreal fade);
    void stopGrowing();
    void clear();
    const std::deque<Part> &parts() const { return m_parts; }

private:
    void add(QPointF pos, qreal now);
    std::deque<Part> m_parts;
    std::optional<Part> m_anchor;
    std::optional<QPointF> m_current;
    std::optional<QPointF> m_stamped;
    qreal m_lastStamp = 0;
    qreal m_nextStamp = 0;
    qreal m_lastMotion = 0;
};
}
