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

#include <KConfig>
#include <KConfigGroup>

#include <QDir>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QFileSystemWatcher>
#include <QPainter>
#include <QProcess>
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
        // Turned on again after being turned off: the app brings the skin cursor back.
        if (QFileInfo::exists(m_directory + QStringLiteral("/effect-off.json"))) {
            runApp(QStringLiteral("effect-on"));
        }
    }

    ~TrailEffect() override
    {
        if (m_ownCursor) {
            effects->showCursor();
        }
        // KWin also unloads effects when the session ends. Only when the user turned
        // the effect off does kwinrc stop saying it is enabled, then the app puts
        // the previous cursor back.
        if (!enabledInSettings()) {
            runApp(QStringLiteral("effect-off"));
        }
    }

    bool isActive() const override
    {
        return m_ownCursor || m_pending.has_value() || !m_parts.parts().empty();
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
            checkMagnified();
            advanceClock();
            const qreal now = time();
            const QPointF pointer = m_mouse->pos();
            if (suppressed(pointer)) {
                clear();
            } else {
                const auto point = std::exchange(m_pending, std::nullopt);
                if (point && matchesSkin()) {
                    m_parts.move(*m_config, *point, now);
                }
                m_parts.stamp(*m_config, now);
                m_parts.expire(now, m_config->fade());
                m_bounds = {};
                for (const Part &part : m_parts.parts()) {
                    m_bounds = m_bounds.united(m_config->stamp(part.pos));
                }
            }
        }
        data.paint |= damage(previous);
        data.paint |= damage(m_bounds);
        if (m_ownCursor) {
            const QRectF previousCursor = std::exchange(m_cursorRect, cursorRect(m_mouse->pos()));
            data.paint |= damage(previousCursor);
            data.paint |= damage(m_cursorRect);
        }
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
        paintOwnCursor(target, viewport, deviceRegion);
        return true;
    }
#else
    void paintScreen(const RenderTarget &target, const RenderViewport &viewport, int mask,
                     const Region &deviceRegion, LogicalOutput *screen) override
    {
        effects->paintScreen(target, viewport, mask, deviceRegion, screen);
        paintTrail(target, viewport, deviceRegion);
        paintOwnCursor(target, viewport, deviceRegion);
    }
#endif

    void postPaintScreen() override
    {
        if (m_running && m_config) {
            if ((m_parts.parts().empty() && !m_pending) || m_parts.settled(*m_config, time())) {
                // Nothing changes until the cursor moves again, so the screen can go idle.
                m_running = false;
            } else if (!m_bounds.isEmpty()) {
                effects->addRepaint(damage(m_bounds));
            }
        }
        effects->postPaintScreen();
    }

private:
    static bool enabledInSettings()
    {
        const KConfig kwinrc(QStringLiteral("kwinrc"), KConfig::NoGlobals);
        return KConfigGroup(&kwinrc, QStringLiteral("Plugins"))
            .readEntry(QStringLiteral("osu-cursor-trailEnabled"), false);
    }

    // The cursor theme is changed by the app, which already knows how to do it on Plasma.
    static void runApp(const QString &command)
    {
        const QString app = QStandardPaths::findExecutable(
            QStringLiteral("cursor-for-osu"), {QDir::homePath() + QStringLiteral("/.local/bin")});
        if (app.isEmpty()) {
            return;
        }
        QProcess process;
        process.setProgram(app);
        process.setArguments({command});
        QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
        environment.insert(QStringLiteral("XDG_CURRENT_DESKTOP"), QStringLiteral("KDE"));
        environment.insert(QStringLiteral("XDG_SESSION_TYPE"), QStringLiteral("wayland"));
        process.setProcessEnvironment(environment);
        process.startDetached();
    }

    // When KWin draws the cursor into the scene instead of on its own hardware plane,
    // which happens on some GPUs, the trail would land on top of it. So while the skin
    // cursor is shown, the real one is hidden and drawn here, after the trail, like osu!.
    QRectF cursorRect(QPointF pos) const
    {
        if (m_cursorImage.isNull()) {
            return {};
        }
        return QRectF(pos - m_cursorHotspot, QSizeF(m_cursorImage.size()) / m_cursorImage.devicePixelRatio());
    }

    void loadCursorImage()
    {
        const PlatformCursorImage cursor = effects->cursorImage();
        m_cursorImage = cursor.image();
        m_cursorHotspot = cursor.hotSpot();
        if (m_cursorTexture) {
            effects->makeOpenGLContextCurrent();
            m_cursorTexture.reset();
        }
    }

    void updateOwnCursor()
    {
        const QPointF pos = m_mouse->pos();
        const bool wanted = m_config && !suppressed(pos) && matchesSkin();
        if (wanted == m_ownCursor) {
            return;
        }
        // Set first: hiding the cursor emits hiddenChanged, which comes back here.
        m_ownCursor = wanted;
        if (wanted) {
            loadCursorImage();
            effects->hideCursor();
        } else {
            effects->showCursor();
        }
        m_cursorRect = cursorRect(pos);
        effects->addRepaint(damage(m_cursorRect));
    }

    void paintOwnCursor(const RenderTarget &target, const RenderViewport &viewport, const Region &deviceRegion)
    {
        if (!m_ownCursor || m_cursorImage.isNull() || !viewport.renderRect().intersects(RectF(m_cursorRect))) {
            return;
        }
        const Region visible = deviceRegion.intersected(viewport.deviceRect()).intersected(target.transformedRect());
        if (effects->compositingType() == QPainterCompositing) {
#ifdef KWIN_PAINT_RETURNS_BOOL
            QImage *image = target.image();
            if (!image || image->isNull()) {
                return;
            }
            QPainter painter(image);
            const qreal inverseDpr = 1.0 / image->devicePixelRatio();
            painter.scale(inverseDpr, inverseDpr);
            QRegion clip;
            for (const Rect &rect : visible.rects()) {
                clip += QRect(rect);
            }
            painter.setClipRegion(clip);
            painter.drawImage(QRectF(viewport.mapToDeviceCoordinates(RectF(m_cursorRect))), m_cursorImage);
#else
            QPainter *painter = effects->scenePainter();
            painter->save();
            QRegion clip;
            for (const Rect &rect : visible.rects()) {
                clip += QRect(viewport.mapFromDeviceCoordinatesContained(rect));
            }
            painter->setClipRegion(clip, Qt::IntersectClip);
            painter->drawImage(m_cursorRect, m_cursorImage);
            painter->restore();
#endif
            return;
        }
        if (!m_cursorTexture) {
            m_cursorTexture = GLTexture::upload(m_cursorImage);
            if (!m_cursorTexture) {
                return;
            }
            m_cursorTexture->setFilter(GL_LINEAR);
            m_cursorTexture->setWrapMode(GL_CLAMP_TO_EDGE);
        }
        const Rect device = viewport.mapToDeviceCoordinatesAligned(RectF(m_cursorRect));
        const Region clip = visible.intersected(device);
        if (clip.isEmpty()) {
            return;
        }
        ShaderBinder shader(ShaderTrait::MapTexture | ShaderTrait::TransformColorspace);
        shader.shader()->setColorspaceUniforms(ColorDescription::sRGB, target.colorDescription(),
                                               RenderingIntent::Perceptual);
        // Whole device pixels, so the cursor stays as sharp as KWin's own.
        QMatrix4x4 matrix = viewport.projectionMatrix();
        const qreal scale = viewport.scale();
        matrix.translate(std::round(m_cursorRect.x() * scale), std::round(m_cursorRect.y() * scale));
        shader.shader()->setUniform(GLShader::Mat4Uniform::ModelViewProjectionMatrix, matrix);
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
        glEnable(GL_SCISSOR_TEST);
        m_cursorTexture->render(viewport.transform().map(clip, target.transformedSize()),
                                m_cursorRect.size() * scale, true);
        glDisable(GL_SCISSOR_TEST);
        glDisable(GL_BLEND);
    }

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

    // Trail time: it only runs while the trail changes. Stopped at rest, it picks up
    // where it left off, so a rest is never mistaken for missed frames.
    qreal time() const { return m_time; }

    qreal wallTime() const { return m_clock.nsecsElapsed() / 1000000.0; }

    void startClock()
    {
        if (!m_running) {
            m_running = true;
            m_lastWall = wallTime();
        }
    }

    void advanceClock()
    {
        if (m_running) {
            const qreal wall = wallTime();
            m_time += wall - m_lastWall;
            m_lastWall = wall;
        }
    }

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
        m_running = false;
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
        updateOwnCursor();
    }

    bool suppressed(QPointF pos) const
    {
        if (!m_config || effects->isScreenLocked() || effects->hasActiveFullScreenEffect()
            || (effects->isCursorHidden() && !m_ownCursor) || !m_mouse->source() || m_mouse->source()->isBlank()
            || m_mouse->themeName() != m_config->theme) {
            return true;
        }
        const auto windows = effects->stackingOrder();
        return std::any_of(windows.begin(), windows.end(), [pos](const EffectWindow *window) {
            return window->isFullScreen() && window->isVisible() && window->isOnCurrentDesktop()
                && window->isOnCurrentActivity() && window->frameGeometry().contains(pos);
        });
    }

    // Plasma's shake cursor effect draws a larger cursor into the scene while the
    // pointer is shaken, and the trail would be drawn over it. So that cursor counts
    // as another shape: the trail fades out and comes back once it is small again.
    static bool magnified()
    {
        return effects->isEffectActive(QStringLiteral("shakecursor"));
    }

    // The shake effect gives no signal when it starts, so this is looked at as the
    // pointer moves and on each frame. It ends by showing the cursor again, which
    // already comes back through hiddenChanged.
    void checkMagnified()
    {
        if (magnified() != m_magnified) {
            cursorChanged();
        }
    }

    bool matchesSkin() const
    {
        if (m_magnified) {
            return false;
        }
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
        m_magnified = magnified();
        if (m_ownCursor) {
            loadCursorImage();
            effects->addRepaint(damage(m_cursorRect));
        }
        updateOwnCursor();
        if (suppressed(m_mouse->pos())) {
            clear();
        } else if (!matchesSkin()) {
            // Another cursor shape: no new parts, the ones on screen fade out.
            m_pending.reset();
            m_parts.stopGrowing();
            startClock();
            effects->addRepaint(damage(m_bounds));
        }
    }

    void pointerMoved(QPointF pos)
    {
        checkMagnified();
        updateOwnCursor();
        if (m_ownCursor) {
            effects->addRepaint(damage(m_cursorRect));
            effects->addRepaint(damage(cursorRect(pos)));
        }
        if (suppressed(pos)) {
            clear();
        } else if (matchesSkin()) {
            startClock();
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
    qreal m_time = 0;
    qreal m_lastWall = 0;
    bool m_running = false;
    bool m_invalid = false;
    std::optional<TrailConfig> m_config;
    std::unique_ptr<GLTexture> m_texture;
    TrailParts m_parts;
    std::optional<QPointF> m_pending;
    QRectF m_bounds;
    bool m_ownCursor = false;
    bool m_magnified = false;
    QImage m_cursorImage;
    QPointF m_cursorHotspot;
    std::unique_ptr<GLTexture> m_cursorTexture;
    QRectF m_cursorRect;
};

KWIN_EFFECT_FACTORY_SUPPORTED(TrailEffect, "metadata.json",
                              return effects && effects->waylandDisplay()
                                  && effects->compositingType() != NoCompositing;)

#include "trail.moc"
