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

class TrailParts
{
public:
    void move(const TrailConfig &config, QPointF pos, qreal now);
    void expire(qreal now, qreal fade);
    void stopGrowing();
    void clear();
    const std::deque<Part> &parts() const { return m_parts; }

private:
    void add(QPointF pos, qreal now);
    std::deque<Part> m_parts;
    std::optional<Part> m_anchor;
};
}
