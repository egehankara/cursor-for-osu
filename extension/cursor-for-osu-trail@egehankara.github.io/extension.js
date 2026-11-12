// Trail behaviour ported from osu!lazer's CursorTrail and LegacyCursorTrail.
// Copyright (c) ppy Pty Ltd <contact@ppy.sh>. Licensed under the MIT Licence.

import Clutter from 'gi://Clutter';
import Cogl from 'gi://Cogl';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Graphene from 'gi://Graphene';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const MAX_PARTS = 2048;
const ALPHA_LEVELS = 64;
const DISJOINT_FADE_MS = 150;
const CONTINUOUS_FADE_MS = 500;
const DISJOINT_SEPARATION_MS = 1000 / 60;
const BLEND_ADDITIVE = 'RGBA = ADD(SRC_COLOR, DST_COLOR)';
const BLEND_NORMAL = 'RGBA = ADD(SRC_COLOR, DST_COLOR * (1 - SRC_COLOR[A]))';

const TrailActor = GObject.registerClass(
class OsuCursorTrailActor extends Clutter.Actor {
    _init() {
        super._init({reactive: false, visible: false});
        this._xs = new Float32Array(MAX_PARTS);
        this._ys = new Float32Array(MAX_PARTS);
        this._born = new Float64Array(MAX_PARTS).fill(-Infinity);
        this._next = 0;
        this._alive = 0;
        this._clock = 0;
        this._pipelines = null;
        this._config = null;
        this._bounds = null;
    }

    get hasConfig() {
        return this._config !== null;
    }

    get config() {
        return this._config;
    }

    get clock() {
        return this._clock;
    }

    setSkin(config, pipelines) {
        this._config = config;
        this._pipelines = pipelines;
        this.clear();
    }

    clear() {
        this._born.fill(-Infinity);
        this._next = 0;
        this._alive = 0;
        this._bounds = null;
        this.invalidate_paint_volume();
    }

    addPart(x, y, born = this._clock) {
        this._xs[this._next] = x;
        this._ys[this._next] = y;
        this._born[this._next] = born;
        this._next = (this._next + 1) % MAX_PARTS;
    }

    // Moves the trail clock, which only runs while the trail is animating.
    advance(milliseconds) {
        this._clock += milliseconds;
    }

    // Recounts live parts and the screen area they cover. Returns the live count.
    refresh() {
        const {fade, margin} = this._config;
        let alive = 0;
        let left = Infinity;
        let top = Infinity;
        let right = -Infinity;
        let bottom = -Infinity;

        for (let i = 0; i < MAX_PARTS; i++) {
            if (this._clock - this._born[i] >= fade)
                continue;
            alive++;
            const x = this._xs[i];
            const y = this._ys[i];
            if (x < left)
                left = x;
            if (x > right)
                right = x;
            if (y < top)
                top = y;
            if (y > bottom)
                bottom = y;
        }

        this._alive = alive;
        this._bounds = alive > 0
            ? {x: left - margin, y: top - margin, width: right - left + 2 * margin, height: bottom - top + 2 * margin}
            : null;
        // Clutter caches the paint volume and would keep redrawing the old area.
        this.invalidate_paint_volume();
        return alive;
    }

    vfunc_get_paint_volume(volume) {
        if (!this._bounds)
            return false;
        volume.set_origin(new Graphene.Point3D({x: this._bounds.x, y: this._bounds.y, z: 0}));
        volume.set_width(this._bounds.width);
        volume.set_height(this._bounds.height);
        return true;
    }

    vfunc_paint(paintContext) {
        if (!this._config || this._alive === 0)
            return;

        const framebuffer = paintContext.get_framebuffer();
        const {fade, width, height, offsetX, offsetY} = this._config;
        const x1 = -offsetX;
        const y1 = -offsetY;
        const x2 = x1 + width;
        const y2 = y1 + height;

        // Starting at the write position draws the oldest parts first.
        for (let n = 0; n < MAX_PARTS; n++) {
            const i = (this._next + n) % MAX_PARTS;
            const age = this._clock - this._born[i];
            if (age >= fade)
                continue;

            const alpha = 1 - age / fade;
            const level = Math.min(ALPHA_LEVELS - 1, Math.round(alpha * (ALPHA_LEVELS - 1)));
            if (level === 0)
                continue;
            const pipeline = this._pipelines[level];
            const x = this._xs[i];
            const y = this._ys[i];

            framebuffer.draw_textured_rectangle(pipeline, x + x1, y + y1, x + x2, y + y2, 0, 0, 1, 1);
        }
    }
});

class Trail {
    constructor(dataDir) {
        this._statePath = GLib.build_filenamev([dataDir, 'state.json']);
        this._dataDir = dataDir;
        this._last = null;
        this._current = null;
        this._lastStamp = 0;
        this._nextStamp = 0;
        this._moved = false;
        this._stamped = null;
        this._lastMotion = 0;
        this._frameTime = null;

        this._actor = new TrailActor();
        this._actor.add_constraint(new Clutter.BindConstraint({
            source: global.stage,
            coordinate: Clutter.BindCoordinate.SIZE,
        }));
        global.stage.add_child(this._actor);

        // The repeating timeline is only used as a per-frame callback.
        this._timeline = new Clutter.Timeline({actor: this._actor, duration: 1000, repeat_count: -1});
        this._frameId = this._timeline.connect('new-frame', () => this._onFrame());

        this._tracker = global.backend.get_cursor_tracker();
        this._motionId = this._tracker.connect('position-invalidated', () => this._onMotion());
        this._cursorId = this._tracker.connect('cursor-changed', () => this._updateCursorVisible());
        this._fullscreenId = global.display.connect('in-fullscreen-changed', () => this._hideIfSuppressed());
        this._cursorVisible = true;
        this._skinCursor = null;
        this._updateCursorVisible();

        const directory = Gio.File.new_for_path(dataDir);
        try {
            directory.make_directory_with_parents(null);
        } catch (error) {
            if (!error.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.EXISTS))
                throw error;
        }
        this._monitor = directory.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, null);
        this._monitorId = this._monitor.connect('changed', (_monitor, file, other) => {
            if (file.get_basename() === 'state.json' || other?.get_basename() === 'state.json')
                this._scheduleLoad();
        });
        this._loadId = 0;
        this._load();
    }

    destroy() {
        if (this._loadId)
            GLib.source_remove(this._loadId);
        this._monitor.disconnect(this._monitorId);
        this._monitor.cancel();
        this._tracker.disconnect(this._motionId);
        this._tracker.disconnect(this._cursorId);
        global.display.disconnect(this._fullscreenId);
        this._timeline.disconnect(this._frameId);
        this._timeline.stop();
        this._actor.destroy();
    }

    _scheduleLoad() {
        if (this._loadId)
            return;
        this._loadId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => {
            this._loadId = 0;
            this._load();
            return GLib.SOURCE_REMOVE;
        });
    }

    _load() {
        this._stop();
        this._last = null;
        this._current = null;
        this._skinCursor = null;
        try {
            const [, stateBytes] = GLib.file_get_contents(this._statePath);
            const state = JSON.parse(new TextDecoder().decode(stateBytes));
            this._skinCursor = state.skin_cursor ?? null;
            this._updateCursorVisible();
            if (state.trail && state.trail_enabled !== false) {
                this._applyTrail(state.trail);
                return;
            }
        } catch (error) {
            if (!error.matches?.(GLib.FileError, GLib.FileError.NOENT))
                console.error(`osu-cursor: could not load the trail: ${error}`);
        }
        this._actor.setSkin(null, null);
    }

    _applyTrail(trail) {
        const path = GLib.build_filenamev([this._dataDir, GLib.path_get_basename(trail.file)]);
        const [, pixels] = GLib.file_get_contents(path);
        if (pixels.length !== trail.width * trail.height * 4)
            throw new Error('trail image has the wrong size');

        const context = global.stage.context.get_backend().get_cogl_context();
        const texture = Cogl.Texture2D.new_from_data(
            context, trail.width, trail.height, Cogl.PixelFormat.RGBA_8888_PRE, trail.width * 4, pixels);

        const base = Cogl.Pipeline.new(context);
        base.set_layer_texture(0, texture);
        // The game samples textures through mipmaps, which keeps shrunken trails smooth.
        base.set_layer_filters(0, Cogl.PipelineFilter.LINEAR_MIPMAP_LINEAR, Cogl.PipelineFilter.LINEAR);
        base.set_blend(trail.disjoint ? BLEND_NORMAL : BLEND_ADDITIVE);

        // One pipeline per alpha step lets Cogl batch the rectangles.
        const pipelines = [];
        for (let level = 0; level < ALPHA_LEVELS; level++) {
            const alpha = level / (ALPHA_LEVELS - 1);
            const color = new Cogl.Color();
            color.init_from_4f(alpha, alpha, alpha, alpha);
            const pipeline = base.copy();
            pipeline.set_color(color);
            pipelines.push(pipeline);
        }

        const offsetX = trail.centre ? trail.display_width / 2 : 0;
        const offsetY = trail.centre ? trail.display_height / 2 : 0;
        const reachX = Math.max(offsetX, trail.display_width - offsetX);
        const reachY = Math.max(offsetY, trail.display_height - offsetY);
        this._actor.setSkin({
            width: trail.display_width,
            height: trail.display_height,
            offsetX,
            offsetY,
            interval: Math.max(trail.interval, 0.5),
            disjoint: trail.disjoint,
            fade: trail.disjoint ? DISJOINT_FADE_MS : CONTINUOUS_FADE_MS,
            margin: Math.ceil(Math.hypot(reachX, reachY)) + 2,
        }, pipelines);
    }

    _pointer() {
        const [point] = this._tracker.get_pointer();
        return point;
    }

    _updateCursorVisible() {
        const sprite = this._tracker.get_sprite();
        this._cursorVisible = sprite !== null && this._showsSkinCursor(sprite);
        this._hideIfSuppressed();
    }

    // When system cursors are kept, text, resize and the like get no trail.
    // The skin cursor is told apart by its size and hotspot.
    _showsSkinCursor(sprite) {
        const own = this._skinCursor;
        if (!own)
            return true;
        const [hotX, hotY] = this._tracker.get_hot();
        return sprite.get_width() === own.width && sprite.get_height() === own.height &&
            hotX === own.hot_x && hotY === own.hot_y;
    }

    // No trail over fullscreen windows. While an application hides the cursor
    // or a kept system cursor is shown, the trail stops growing and fades out.
    _hideIfSuppressed() {
        if (Main.layoutManager.currentMonitor?.inFullscreen) {
            // Motion keeps arriving during a fullscreen game, so only clean up once.
            if (this._actor.visible)
                this._stop();
            this._last = null;
            this._current = null;
            return true;
        }
        if (this._cursorVisible)
            return false;
        if (this._last || this._current)
            this._fadeOut();
        return true;
    }

    // Draws the trail up to where the cursor changed shape, then lets the parts
    // already on screen age out instead of wiping them at once.
    _fadeOut() {
        if (this._actor.hasConfig && this._actor.visible) {
            const point = this._pointer();
            if (this._actor.config.disjoint) {
                this._current = {x: point.x, y: point.y};
                this._stampDisjoint(this._actor.clock, this._actor.config.fade);
            } else {
                this._addInterpolated(point.x, point.y);
            }
            // A resting trail has its clock stopped, so it must run again to fade.
            this._start();
        }
        this._moved = false;
        this._last = null;
        this._current = null;
        // The next trail starts where the cursor comes back, not from here.
        this._stamped = null;
    }

    // A mouse can report a thousand times a second, but only one position per
    // frame can be drawn. The frame reads the pointer, this only asks for one.
    _onMotion() {
        if (this._moved || !this._actor.hasConfig || this._hideIfSuppressed())
            return;

        this._moved = true;
        this._start();
    }

    _readPointer(clock) {
        this._moved = false;
        const point = this._pointer();
        if (this._actor.config.disjoint) {
            this._current = {x: point.x, y: point.y};
            this._lastMotion = clock;
        } else {
            this._addInterpolated(point.x, point.y);
        }
    }

    // Lines the parts up along the movement, keeping the distance left over for
    // the next event. The last interval is skipped to stay clear of the cursor.
    _addInterpolated(x, y) {
        if (!this._last) {
            this._last = {x, y};
            return;
        }

        const start = this._last;
        const dx = x - start.x;
        const dy = y - start.y;
        const distance = Math.hypot(dx, dy);
        if (distance === 0)
            return;

        const {interval} = this._actor.config;
        const stopAt = distance - interval;
        for (let d = interval; d < stopAt; d += interval) {
            this._last = {x: start.x + dx / distance * d, y: start.y + dy / distance * d};
            this._actor.addPart(this._last.x, this._last.y);
        }
    }

    // The game stamps a part every 1/60 s, but a busy compositor can draw much less
    // often. Parts missed in between are added along the path, already aged.
    _stampDisjoint(clock, fade) {
        const {x, y} = this._current;
        const from = this._stamped;
        const elapsed = clock - this._lastStamp;

        if (from) {
            const missing = Math.round(elapsed / DISJOINT_SEPARATION_MS) - 1;
            const longest = Math.ceil(fade / DISJOINT_SEPARATION_MS) - 1;
            for (let k = Math.min(missing, longest); k >= 1; k--) {
                const age = k * DISJOINT_SEPARATION_MS;
                const along = 1 - age / elapsed;
                this._actor.addPart(from.x + (x - from.x) * along, from.y + (y - from.y) * along, clock - age);
            }
        }
        this._actor.addPart(x, y);

        // Rest detection must wait for these parts to fade, or they would freeze on screen.
        if (!from || from.x !== x || from.y !== y)
            this._lastMotion = clock;
        this._lastStamp = clock;
        // Staying on a 60 Hz grid keeps the rate exact however frames fall around it.
        this._nextStamp = clock + DISJOINT_SEPARATION_MS - (clock - this._nextStamp) % DISJOINT_SEPARATION_MS;
        this._stamped = {x, y};
    }

    _start() {
        if (this._timeline.is_playing())
            return;
        this._frameTime = GLib.get_monotonic_time();
        this._actor.show();
        this._timeline.start();
    }

    _stop() {
        this._moved = false;
        this._stamped = null;
        this._timeline.stop();
        this._actor.clear();
        this._actor.hide();
    }

    _onFrame() {
        const config = this._actor.config;
        if (!config)
            return;

        const now = GLib.get_monotonic_time();
        this._actor.advance((now - this._frameTime) / 1000);
        this._frameTime = now;

        const clock = this._actor.clock;
        if (this._moved)
            this._readPointer(clock);

        if (config.disjoint && this._current && clock >= this._nextStamp)
            this._stampDisjoint(clock, config.fade);

        const alive = this._actor.refresh();
        this._actor.queue_redraw();

        if (alive === 0) {
            this._timeline.stop();
            this._actor.hide();
        } else if (config.disjoint && this._current &&
            clock - this._lastMotion > config.fade + DISJOINT_SEPARATION_MS) {
            // A resting cursor keeps a steady stack of parts under it, which never
            // changes, so the clock can stop and the screen can go idle.
            this._timeline.stop();
        }
    }
}

export default class OsuCursorTrailExtension extends Extension {
    enable() {
        this._trail = new Trail(GLib.build_filenamev([GLib.get_user_data_dir(), 'osu-cursor']));
    }

    disable() {
        this._trail.destroy();
        this._trail = null;
    }
}
