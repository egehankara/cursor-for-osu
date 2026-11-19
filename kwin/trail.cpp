#include "trailstate.h"

#include <core/rendertarget.h>
#include <core/renderviewport.h>
#include <cursor.h>
#include <cursorsource.h>
#include <effect/effect.h>
#include <effect/effecthandler.h>
#include <effect/effectwindow.h>
#include <opengl/glshader.h>
#include <opengl/glshadermanager.h>
#include <opengl/gltexture.h>

#include <QElapsedTimer>
#include <QFileInfo>
#include <QFileSystemWatcher>
#include <QPainter>
#include <QStandardPaths>
#include <QTimer>

#include <algorithm>
#include <cmath>
#include <memory>
#include <utility>

using namespace KWin;
using namespace OsuCursor;

class TrailEffect : public Effect
{
public:
    TrailEffect()
        : m_directory(QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation)
                      + QStringLiteral("/osu-cursor/plasma"))
        , m_mouse(Cursors::self()->mouse())
    {
        m_clock.start();
        connect(m_mouse, &Cursor::posChanged, this, &TrailEffect::pointerMoved);
        connect(m_mouse, &Cursor::cursorChanged, this, &TrailEffect::cursorChanged);
        connect(m_mouse, &Cursor::themeChanged, this, &TrailEffect::cursorChanged);
        connect(Cursors::self(), &Cursors::hiddenChanged, this, &TrailEffect::cursorChanged);
        connect(effects, &EffectsHandler::screenLockingChanged, this, &TrailEffect::cursorChanged);
        connect(effects, &EffectsHandler::hasActiveFullScreenEffectChanged, this, &TrailEffect::cursorChanged);
        m_reloadTimer.setSingleShot(true);
        m_reloadTimer.setInterval(30);
        connect(&m_watcher, &QFileSystemWatcher::directoryChanged, &m_reloadTimer, qOverload<>(&QTimer::start));
        connect(&m_reloadTimer, &QTimer::timeout, this, &TrailEffect::reload);
        reload();
    }

    bool isActive() const override
    {
        return m_pending.has_value() || !m_parts.parts().empty();
    }

    QString debug(const QString &parameter) const override
    {
        if (parameter == QStringLiteral("state")) {
            if (m_invalid) {
                return QStringLiteral("invalid");
            }
            return m_config ? QStringLiteral("ready") : QStringLiteral("inactive");
        }
        return Effect::debug(parameter);
    }

#ifdef KWIN_PREPAINT_WITHOUT_TIMESTAMP
    void prePaintScreen(ScreenPrePaintData &data) override
#else
    void prePaintScreen(ScreenPrePaintData &data, std::chrono::milliseconds presentTime) override
#endif
    {
        const QRectF previous = m_bounds;
        if (m_config && isActive()) {
            const qreal now = time();
            const QPointF pointer = m_mouse->pos();
            if (suppressed(pointer)) {
                clear();
            } else {
                const auto point = std::exchange(m_pending, std::nullopt);
                if (point && matchesSkin()) {
                    m_parts.move(*m_config, *point, now);
                }
                m_parts.expire(now, m_config->fade());
                m_bounds = {};
                for (const Part &part : m_parts.parts()) {
                    m_bounds = m_bounds.united(m_config->stamp(part.pos));
                }
            }
        }
        data.paint |= damage(previous);
        data.paint |= damage(m_bounds);
#ifdef KWIN_PREPAINT_WITHOUT_TIMESTAMP
        effects->prePaintScreen(data);
#else
        effects->prePaintScreen(data, presentTime);
#endif
    }

#ifdef KWIN_PAINT_RETURNS_BOOL
    bool paintScreen(const RenderTarget &target, const RenderViewport &viewport, int mask,
                     const Region &deviceRegion, LogicalOutput *screen) override
    {
        if (!effects->paintScreen(target, viewport, mask, deviceRegion, screen)) {
            return false;
        }
        paintTrail(target, viewport, deviceRegion);
        return true;
    }
#else
    void paintScreen(const RenderTarget &target, const RenderViewport &viewport, int mask,
                     const Region &deviceRegion, LogicalOutput *screen) override
    {
        effects->paintScreen(target, viewport, mask, deviceRegion, screen);
        paintTrail(target, viewport, deviceRegion);
    }
#endif

    void postPaintScreen() override
    {
        if (!m_bounds.isEmpty()) {
            effects->addRepaint(damage(m_bounds));
        }
        effects->postPaintScreen();
    }

private:
    void paintTrail(const RenderTarget &target, const RenderViewport &viewport, const Region &deviceRegion)
    {
        if (m_parts.parts().empty() || !viewport.renderRect().intersects(RectF(m_bounds))) {
            return;
        }
        if (effects->compositingType() == QPainterCompositing) {
#ifdef KWIN_PAINT_RETURNS_BOOL
            paintSoftware(target, viewport, deviceRegion);
#else
            paintSoftware(viewport, deviceRegion);
#endif
            return;
        }
        if (!m_texture) {
            m_texture = GLTexture::upload(m_config->texture);
            if (!m_texture) {
                m_invalid = true;
                clear();
                m_config.reset();
                return;
            }
            m_texture->setFilter(GL_LINEAR);
            m_texture->setWrapMode(GL_CLAMP_TO_EDGE);
        }

        ShaderBinder shader(ShaderTrait::MapTexture | ShaderTrait::Modulate | ShaderTrait::TransformColorspace);
        shader.shader()->setColorspaceUniforms(ColorDescription::sRGB, target.colorDescription(),
                                               RenderingIntent::Perceptual);
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE, m_config->disjoint ? GL_ONE_MINUS_SRC_ALPHA : GL_ONE);
        glEnable(GL_SCISSOR_TEST);
        const qreal scale = viewport.scale();
        const qreal now = time();
        const Region visible = deviceRegion.intersected(viewport.deviceRect()).intersected(target.transformedRect());
        for (const Part &part : m_parts.parts()) {
            const QRectF rect = m_config->stamp(part.pos);
            const Rect stamp = viewport.mapToDeviceCoordinatesAligned(RectF(rect));
            const Region clip = visible.intersected(stamp);
            if (clip.isEmpty()) {
                continue;
            }
            const float alpha = opacity(part, now);
            QMatrix4x4 matrix = viewport.projectionMatrix();
            matrix.translate(rect.x() * scale, rect.y() * scale);
            shader.shader()->setUniform(GLShader::Mat4Uniform::ModelViewProjectionMatrix, matrix);
            shader.shader()->setUniform(GLShader::Vec4Uniform::ModulationConstant, QVector4D(alpha, alpha, alpha, alpha));
            const Region bufferClip = viewport.transform().map(clip, target.transformedSize());
            m_texture->render(bufferClip, rect.size() * scale, true);
        }
        glDisable(GL_SCISSOR_TEST);
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
        glDisable(GL_BLEND);
    }

    qreal time() const { return m_clock.nsecsElapsed() / 1000000.0; }

    qreal opacity(const Part &part, qreal now) const
    {
        return std::clamp(1.0 - (now - part.born) / m_config->fade(), 0.0, 1.0);
    }

#ifdef KWIN_PAINT_RETURNS_BOOL
    void paintSoftware(const RenderTarget &target, const RenderViewport &viewport, const Region &deviceRegion)
    {
        QImage *image = target.image();
        if (!image || image->isNull()) {
            return;
        }
        QPainter painter(image);
        const qreal inverseDpr = 1.0 / image->devicePixelRatio();
        painter.scale(inverseDpr, inverseDpr);
        QRegion clip;
        const Region visible = deviceRegion.intersected(viewport.deviceRect()).intersected(target.transformedRect());
        for (const Rect &rect : visible.rects()) {
            clip += QRect(rect);
        }
        paintSoftwareParts(painter, clip, [&viewport](const QRectF &stamp) {
            return QRectF(viewport.mapToDeviceCoordinates(RectF(stamp)));
        });
    }
#else
    void paintSoftware(const RenderViewport &viewport, const Region &deviceRegion)
    {
        QRegion clip;
        const Region visible = deviceRegion.intersected(viewport.deviceRect());
        for (const Rect &rect : visible.rects()) {
            clip += QRect(viewport.mapFromDeviceCoordinatesContained(rect));
        }
        QPainter *painter = effects->scenePainter();
        painter->save();
        paintSoftwareParts(*painter, clip, [](const QRectF &stamp) { return stamp; });
        painter->restore();
    }
#endif

    void paintSoftwareParts(QPainter &painter, const QRegion &clip, auto mapStamp)
    {
        painter.setClipRegion(clip, Qt::IntersectClip);
        painter.setRenderHint(QPainter::SmoothPixmapTransform);
        painter.setCompositionMode(m_config->disjoint ? QPainter::CompositionMode_SourceOver
                                                      : QPainter::CompositionMode_Plus);
        const qreal now = time();
        for (const Part &part : m_parts.parts()) {
            painter.setOpacity(opacity(part, now));
            painter.drawImage(mapStamp(m_config->stamp(part.pos)), m_config->texture);
        }
    }

    static Rect damage(const QRectF &bounds)
    {
        return bounds.isEmpty() ? Rect() : Rect(bounds.adjusted(-1, -1, 1, 1).toAlignedRect());
    }

    void clear()
    {
        m_pending.reset();
        m_parts.clear();
        if (!m_bounds.isEmpty()) {
            effects->addRepaint(damage(m_bounds));
            m_bounds = {};
        }
    }

    void reload()
    {
        // Watch the parent as well, so uninstall/reinstall can replace the state directory.
        const auto watched = m_watcher.directories();
        QString path = m_directory;
        for (int depth = 0; depth < 3; ++depth) {
            if (QFileInfo(path).isDir() && !watched.contains(path)) {
                m_watcher.addPath(path);
            }
            path = QFileInfo(path).absolutePath();
        }
        clear();
        if (m_texture) {
            effects->makeOpenGLContextCurrent();
            m_texture.reset();
        }
        m_config = readTrail(m_directory, m_invalid);
    }

    bool suppressed(QPointF pos) const
    {
        if (!m_config || effects->isScreenLocked() || effects->hasActiveFullScreenEffect()
            || effects->isCursorHidden() || !m_mouse->source() || m_mouse->source()->isBlank()
            || m_mouse->themeName() != m_config->theme) {
            return true;
        }
        const auto windows = effects->stackingOrder();
        return std::any_of(windows.begin(), windows.end(), [pos](const EffectWindow *window) {
            return window->isFullScreen() && window->isVisible() && window->isOnCurrentDesktop()
                && window->isOnCurrentActivity() && window->frameGeometry().contains(pos);
        });
    }

    bool matchesSkin() const
    {
        if (m_config->cursorSize.isEmpty()) {
            return true;
        }
        // Wayland clients may supply their own cursor surface. Compare its
        // logical size and hotspot, as the GNOME extension does.
        const QSizeF size = m_mouse->source()->size();
        const QPointF hotspot = m_mouse->hotspot();
        return std::abs(size.width() - m_config->cursorSize.width()) < 1
            && std::abs(size.height() - m_config->cursorSize.height()) < 1
            && std::abs(hotspot.x() - m_config->hotspot.x()) < 1
            && std::abs(hotspot.y() - m_config->hotspot.y()) < 1;
    }

    void cursorChanged()
    {
        if (suppressed(m_mouse->pos())) {
            clear();
        } else if (!matchesSkin()) {
            m_pending.reset();
            m_parts.stopGrowing();
        }
    }

    void pointerMoved(QPointF pos)
    {
        if (suppressed(pos)) {
            clear();
        } else if (matchesSkin()) {
            const bool scheduled = m_pending.has_value();
            m_pending = pos;
            if (!scheduled) {
                effects->addRepaint(damage(m_config->stamp(pos)));
            }
        }
    }

    QString m_directory;
    Cursor *m_mouse;
    QFileSystemWatcher m_watcher;
    QTimer m_reloadTimer;
    QElapsedTimer m_clock;
    bool m_invalid = false;
    std::optional<TrailConfig> m_config;
    std::unique_ptr<GLTexture> m_texture;
    TrailParts m_parts;
    std::optional<QPointF> m_pending;
    QRectF m_bounds;
};

KWIN_EFFECT_FACTORY_SUPPORTED(TrailEffect, "metadata.json",
                              return effects && effects->waylandDisplay()
                                  && effects->compositingType() != NoCompositing;)

#include "trail.moc"
