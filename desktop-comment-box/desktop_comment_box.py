#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import uuid
import fcntl
import socket
import threading
import atexit
import time
try:
    import cairo
except Exception:
    cairo = None
from pathlib import Path
from urllib.parse import urlparse, unquote

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Gio, GLib, Pango, GdkPixbuf

APP_ID = 'desktop-comment-box-gtk'
CONFIG_DIR = Path.home() / '.config' / APP_ID
DATA_DIR = Path.home() / '.local' / 'share' / APP_ID
BOX_DIR = DATA_DIR / 'boxes'
CONFIG_FILE = CONFIG_DIR / 'config.json'
LOCK_FILE = CONFIG_DIR / 'app.lock'
CONTROL_SOCKET = CONFIG_DIR / 'control.sock'
DESKTOP_DIR = Path.home() / 'Desktop'
LOG_DIR = Path.home() / '.cache' / APP_ID
CAPTURE_LOG = LOG_DIR / 'capture.log'
URI_TARGETS = [Gtk.TargetEntry.new('text/uri-list', 0, 0)]

DEFAULTS = {
    'background': '#2f343acc',
    'border': '#80a8ffff',
    'title_color': '#ffffffff',
    'label_color': '#ffffffff',
    'hover': '#ffffff22',
    'window_opacity': 1.0,
    'icon_size': 48,
    'width': 360,
    'height': 260,
    'x': 120,
    'y': 120,
}

MIN_BOX_WIDTH = 180
MIN_BOX_HEIGHT = 140
MAX_BOX_WIDTH = 900
MAX_BOX_HEIGHT = 650
GRID_MARGIN_X = 8
GRID_MARGIN_Y = 8
TITLEBAR_CAPTURE_OFFSET = 46
CAPTURE_BOX_PADDING = 14


STYLE_KEYS = ['background', 'border', 'title_color', 'label_color', 'hover', 'window_opacity', 'icon_size', 'show_hidden']


def new_default_settings():
    return {
        'title': 'New Box',
        'width': DEFAULTS['width'],
        'height': DEFAULTS['height'],
        'background': DEFAULTS['background'],
        'border': DEFAULTS['border'],
        'title_color': DEFAULTS['title_color'],
        'label_color': DEFAULTS['label_color'],
        'hover': DEFAULTS['hover'],
        'window_opacity': DEFAULTS['window_opacity'],
        'icon_size': DEFAULTS['icon_size'],
        'show_hidden': False,
    }


def clamp_size(width, height):
    try:
        width = int(width)
        height = int(height)
    except Exception:
        width, height = DEFAULTS['width'], DEFAULTS['height']
    return (
        max(MIN_BOX_WIDTH, min(MAX_BOX_WIDTH, width)),
        max(MIN_BOX_HEIGHT, min(MAX_BOX_HEIGHT, height)),
    )


def migrate_box_settings(box):
    box.setdefault('positions', {})
    box.setdefault('background', DEFAULTS['background'])
    box.setdefault('border', DEFAULTS['border'])
    box.setdefault('title_color', DEFAULTS['title_color'])
    box.setdefault('label_color', DEFAULTS['label_color'])
    box.setdefault('hover', DEFAULTS['hover'])
    box.setdefault('window_opacity', DEFAULTS['window_opacity'])
    box.setdefault('icon_size', DEFAULTS['icon_size'])
    box.setdefault('show_hidden', False)
    box['width'], box['height'] = clamp_size(box.get('width', DEFAULTS['width']), box.get('height', DEFAULTS['height']))
    return box


def repair_config(cfg):
    """Repair stale config left by earlier multi-instance builds.

    Older builds could accidentally save two visible boxes with the same id or the
    same backing folder.  Those boxes looked synced, and Remove This Box removed
    every config entry with that shared id.  Keep the first real box for each
    folder, generate unique ids where needed, and ensure every surviving box has
    its own folder.
    """
    if not isinstance(cfg, dict):
        cfg = {'defaults': new_default_settings(), 'boxes': []}
    cfg.setdefault('defaults', new_default_settings())
    if not isinstance(cfg.get('boxes'), list):
        cfg['boxes'] = []

    repaired = []
    seen_ids = set()
    seen_folders = set()
    changed = False

    for raw in cfg.get('boxes', []):
        if not isinstance(raw, dict):
            changed = True
            continue
        box = migrate_box_settings(raw)

        box_id = str(box.get('id') or '').strip()
        if not box_id or box_id in seen_ids:
            box_id = str(uuid.uuid4())
            box['id'] = box_id
            changed = True
        seen_ids.add(box_id)

        folder_text = str(box.get('folder') or '').strip()
        if folder_text:
            folder = Path(folder_text).expanduser()
        else:
            folder = BOX_DIR / box_id
            box['folder'] = str(folder)
            changed = True

        try:
            folder_key = str(folder.resolve(strict=False))
        except Exception:
            folder_key = str(folder)

        if folder_key in seen_folders:
            # This is a duplicate/synced ghost entry.  Do not create another box
            # for the same folder; keep the first one.
            changed = True
            continue
        seen_folders.add(folder_key)

        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            folder = BOX_DIR / box_id
            folder.mkdir(parents=True, exist_ok=True)
            box['folder'] = str(folder)
            changed = True

        repaired.append(box)

    cfg['boxes'] = repaired
    cfg['_repaired_at_start'] = bool(changed)
    return cfg


def make_box_from_defaults(defaults, title=None, offset=0):
    box_id = str(uuid.uuid4())
    folder = BOX_DIR / box_id
    folder.mkdir(parents=True, exist_ok=True)
    d = new_default_settings()
    if isinstance(defaults, dict):
        d.update({k: defaults[k] for k in STYLE_KEYS + ['title', 'width', 'height'] if k in defaults})
    return migrate_box_settings({
        'id': box_id,
        'title': title or d.get('title', 'New Box'),
        'folder': str(folder),
        'x': DEFAULTS['x'] + offset,
        'y': DEFAULTS['y'] + offset,
        'width': int(d.get('width', DEFAULTS['width'])),
        'height': int(d.get('height', DEFAULTS['height'])),
        'background': d.get('background', DEFAULTS['background']),
        'border': d.get('border', DEFAULTS['border']),
        'title_color': d.get('title_color', DEFAULTS['title_color']),
        'label_color': d.get('label_color', DEFAULTS['label_color']),
        'hover': d.get('hover', DEFAULTS['hover']),
        'window_opacity': float(d.get('window_opacity', DEFAULTS['window_opacity'])),
        'icon_size': int(d.get('icon_size', DEFAULTS['icon_size'])),
        'show_hidden': bool(d.get('show_hidden', False)),
        'positions': {},
    })


def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    BOX_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)


def log_capture(message):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CAPTURE_LOG, 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {message}\n')
    except Exception:
        pass


def load_config(create_initial=True):
    ensure_dirs()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                return repair_config(cfg)
        except Exception:
            pass
    cfg = {'defaults': new_default_settings(), 'boxes': []}
    if create_initial:
        cfg['boxes'].append(make_box_from_defaults(cfg['defaults'], title='My Icons', offset=0))
    return repair_config(cfg)


def save_config(cfg):
    ensure_dirs()
    tmp = CONFIG_FILE.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)
    tmp.replace(CONFIG_FILE)


def unique_dest(dest_dir: Path, name: str) -> Path:
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    n = 1
    while True:
        c = dest_dir / f'{stem} ({n}){suffix}'
        if not c.exists():
            return c
        n += 1


def uri_to_path(uri: str):
    try:
        parsed = urlparse(uri)
        if parsed.scheme != 'file':
            return None
        return Path(unquote(parsed.path))
    except Exception:
        return None


def _split_capture_token(raw):
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    # Remove one level of shell/Nemo quotes if present.
    if (text.startswith('\"') and text.endswith('\"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()
    candidates = []
    for line in text.replace('\r', '\n').split('\n'):
        line = line.strip()
        if not line:
            continue
        candidates.append(line)
    # v1.3.0 accidentally installed Separator=,, so some systems pass a whole
    # selection as one comma-separated arg.  Only split commas when the combined
    # token is not itself a real file path.
    expanded = []
    for item in candidates:
        if ',' in item and not item.startswith('file://') and not Path(item).expanduser().exists():
            expanded.extend([part.strip() for part in item.split(',') if part.strip()])
        else:
            expanded.append(item)
    return expanded


def normalize_capture_paths(args):
    paths = []
    seen = set()
    for raw in args or []:
        for token in _split_capture_token(raw):
            p = uri_to_path(token) if token.startswith('file://') else Path(token).expanduser()
            try:
                key = str(p.resolve(strict=False))
            except Exception:
                key = str(p)
            if key in seen:
                continue
            seen.add(key)
            paths.append(p)
    return paths


def validate_desktop_capture_selection(paths):
    """Return (valid_paths, rejected_paths).

    Capture is intentionally strict:
    - there must be at least one selected item
    - every selected item must exist
    - every selected item must be a direct child of ~/Desktop
    - ~/Desktop itself is rejected
    - nested/non-desktop paths are rejected
    """
    valid = []
    rejected = []
    seen = set()
    desktop = DESKTOP_DIR.expanduser().resolve(strict=False)
    for p in normalize_capture_paths(paths):
        try:
            raw = Path(p).expanduser()
            resolved = raw.resolve(strict=False)
        except Exception:
            rejected.append(str(p))
            continue
        try:
            if resolved == desktop:
                rejected.append(str(raw))
                continue
            if resolved.parent != desktop:
                rejected.append(str(raw))
                continue
            if not raw.exists():
                rejected.append(str(raw))
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            valid.append(raw)
        except Exception:
            rejected.append(str(raw))
    return valid, rejected


def rgba_css(value: str, fallback: str = '#000000ff') -> str:
    value = (value or fallback).strip()
    try:
        rgba = Gdk.RGBA()
        if not rgba.parse(value):
            rgba.parse(fallback)
        return rgba.to_string()
    except Exception:
        return fallback


def open_path(path: Path):
    try:
        subprocess.Popen(['xdg-open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def move_path_to(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_dest(dest_dir, src.name)
    try:
        if src.resolve() == dest.resolve():
            return dest
    except Exception:
        pass
    shutil.move(str(src), str(dest))
    return dest


def parse_nemo_icon_position(value):
    """Return an (x, y) tuple from Nemo's desktop icon metadata.

    Nemo commonly stores desktop icon coordinates as text like "123,456".
    Some versions append extra fields, so this parser keeps the first two
    integer-looking parts and ignores the rest.
    """
    if not value:
        return None
    text = str(value).strip().replace(';', ',').replace(':', ',').replace(' ', ',')
    parts = [p for p in text.split(',') if p.strip()]
    nums = []
    for part in parts:
        try:
            nums.append(int(float(part.strip())))
        except Exception:
            continue
        if len(nums) >= 2:
            break
    if len(nums) >= 2:
        return nums[0], nums[1]
    return None


def get_nemo_icon_position(path: Path):
    """Read Nemo's saved desktop icon coordinates for a file, if present."""
    attrs = (
        'metadata::nemo-icon-position',
        'metadata::nemo-drop-position',
        'metadata::nautilus-icon-position',
        'metadata::nautilus-drop-position',
    )
    try:
        gfile = Gio.File.new_for_path(str(path))
        info = gfile.query_info(','.join(attrs), Gio.FileQueryInfoFlags.NONE, None)
        for attr in attrs:
            try:
                value = info.get_attribute_as_string(attr)
            except Exception:
                value = None
            pos = parse_nemo_icon_position(value)
            if pos:
                return pos
    except Exception:
        pass
    # Some GVFS metadata calls fail from helper-launched processes.  The gio
    # command usually still sees the same metadata, so keep it as a fallback.
    try:
        out = subprocess.check_output(['gio', 'info', '-a', 'metadata::*', str(path)], text=True, stderr=subprocess.DEVNULL, timeout=1.0)
        for line in out.splitlines():
            if 'icon-position' in line or 'drop-position' in line:
                pos = parse_nemo_icon_position(line.split(':', 1)[-1])
                if pos:
                    return pos
    except Exception:
        pass
    return None



def set_nemo_icon_position(path: Path, root_x, root_y, icon_size=48):
    """Tell Nemo where to place an exported Desktop item.

    root_x/root_y are treated as the desired icon tile top-left. Earlier builds
    guessed by subtracting half the icon size from the pointer location, which
    made exports sometimes snap back near the file's old desktop location. The
    drag code now passes the tile top-left directly using the original press
    offset.
    """
    try:
        x = max(0, int(root_x))
        y = max(0, int(root_y))
    except Exception:
        return
    value = f'{x},{y}'
    attrs = (
        'metadata::nemo-icon-position',
        'metadata::nemo-drop-position',
        'metadata::nautilus-icon-position',
        'metadata::nautilus-drop-position',
    )
    # Gio API path.
    try:
        gfile = Gio.File.new_for_path(str(path))
        info = Gio.FileInfo()
        for attr in attrs:
            try:
                info.set_attribute_string(attr, value)
            except Exception:
                pass
        try:
            gfile.set_attributes_from_info(info, Gio.FileQueryInfoFlags.NONE, None)
        except Exception:
            pass
    except Exception:
        pass
    # gio command fallback.  Different Mint/Nemo builds are inconsistent about
    # what metadata they honor, so set the Nemo and Nautilus names.
    for attr in attrs:
        try:
            subprocess.run(['gio', 'set', '-t', 'string', str(path), attr, value], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.8)
        except Exception:
            pass

def tile_step_for_settings(settings):
    icon = int(settings.get('icon_size', DEFAULTS['icon_size']))
    return max(88, icon + 42), max(88, icon + 48)


def canvas_size_for_settings(settings):
    width, height = clamp_size(settings.get('width', DEFAULTS['width']), settings.get('height', DEFAULTS['height']))
    return max(100, width - 32), max(80, height - 62)


def clamp_position_for_settings(settings, x, y):
    icon = int(settings.get('icon_size', DEFAULTS['icon_size']))
    tile_w = max(80, icon + 38)
    tile_h = max(82, icon + 54)
    canvas_w, canvas_h = canvas_size_for_settings(settings)
    max_x = max(GRID_MARGIN_X, canvas_w - tile_w - GRID_MARGIN_X)
    max_y = max(GRID_MARGIN_Y, canvas_h - tile_h - GRID_MARGIN_Y)
    return max(GRID_MARGIN_X, min(int(x), max_x)), max(GRID_MARGIN_Y, min(int(y), max_y))


def grid_cell_to_xy(settings, gx, gy):
    step_x, step_y = tile_step_for_settings(settings)
    return clamp_position_for_settings(settings, GRID_MARGIN_X + int(gx) * step_x, GRID_MARGIN_Y + int(gy) * step_y)


def xy_to_grid_cell(settings, x, y):
    step_x, step_y = tile_step_for_settings(settings)
    gx = round((int(x) - GRID_MARGIN_X) / step_x)
    gy = round((int(y) - GRID_MARGIN_Y) / step_y)
    canvas_w, canvas_h = canvas_size_for_settings(settings)
    icon = int(settings.get('icon_size', DEFAULTS['icon_size']))
    tile_w = max(80, icon + 38)
    tile_h = max(82, icon + 54)
    max_gx = max(0, (canvas_w - tile_w - GRID_MARGIN_X) // step_x)
    max_gy = max(0, (canvas_h - tile_h - GRID_MARGIN_Y) // step_y)
    return max(0, min(int(gx), int(max_gx))), max(0, min(int(gy), int(max_gy)))


def gdk_origin_xy(gdk_window):
    try:
        origin = gdk_window.get_origin()
        if isinstance(origin, tuple):
            if len(origin) >= 3 and isinstance(origin[0], bool):
                return int(origin[1]), int(origin[2])
            if len(origin) >= 2:
                return int(origin[0]), int(origin[1])
        return int(origin.root_x), int(origin.root_y)
    except Exception:
        return 0, 0


def send_payload_to_running(payload) -> bool:
    """Send a JSON command to the already-running controller process."""
    try:
        if not CONTROL_SOCKET.exists():
            return False
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.75)
        try:
            client.connect(str(CONTROL_SOCKET))
            client.sendall((json.dumps(payload) + '\n').encode('utf-8'))
            try:
                client.recv(16)
            except Exception:
                pass
            return True
        finally:
            client.close()
    except Exception:
        try:
            CONTROL_SOCKET.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def send_command_to_running(command: str) -> bool:
    return send_payload_to_running({'command': command.strip()})


def send_capture_to_running(paths) -> bool:
    norm = normalize_capture_paths(paths)
    log_capture(f'send to running: raw={list(paths or [])!r} normalized={[str(p) for p in norm]!r}')
    return send_payload_to_running({'command': 'capture', 'paths': [str(p) for p in norm]})



class IconTile(Gtk.EventBox):
    def __init__(self, window, path: Path, pos_x: int, pos_y: int):
        super().__init__()
        self.box_window = window
        self.path = path
        self.pos_x = int(pos_x)
        self.pos_y = int(pos_y)
        self.set_visible_window(False)
        self.set_above_child(False)
        self.set_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.ENTER_NOTIFY_MASK |
            Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        self._pressed = False
        self._dragging = False
        self._press_offset = (0, 0)
        self._press_root = (0, 0)
        self._press_tile_pos = (int(pos_x), int(pos_y))
        self._grabbed = False
        self._drag_timeout = None
        self._drag_watchdog = None
        self._drag_preview = None
        self._last_motion_area = None
        self._last_motion_target = None
        self._last_same_box_local = None
        self._last_root = None

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.START)
        outer.set_margin_top(4)
        outer.set_margin_bottom(4)
        outer.set_margin_start(4)
        outer.set_margin_end(4)
        self.add(outer)

        self.image = Gtk.Image()
        self.image.set_pixel_size(window.settings.get('icon_size', 48))
        self._set_icon()
        outer.pack_start(self.image, False, False, 0)

        self.label = Gtk.Label(label=path.name)
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        self.label.set_justify(Gtk.Justification.CENTER)
        self.label.set_max_width_chars(14)
        self.label.set_line_wrap(True)
        self.label.set_lines(2)
        self.label.get_style_context().add_class('dccb-icon-label')
        try:
            self.label.get_style_context().add_class(window.css_label_class)
        except Exception:
            pass
        outer.pack_start(self.label, False, False, 0)

        # Keep each icon tile at a predictable size so moving it cannot change the
        # containing window's requested dimensions.
        icon = int(window.settings.get('icon_size', 48))
        self.set_size_request(max(80, icon + 42), max(84, icon + 62))

        self.connect('button-press-event', self._on_button_press)
        self.connect('button-release-event', self._on_button_release)
        self.connect('motion-notify-event', self._on_motion)
        self.connect('grab-broken-event', self._on_grab_broken)
        self.connect('enter-notify-event', self._on_enter_tile)
        self.connect('leave-notify-event', self._on_leave_tile)

    def _on_enter_tile(self, *_args):
        try:
            self.get_style_context().add_class('dccb-tile-hover')
            self.get_style_context().add_class(self.box_window.css_hover_class)
        except Exception:
            pass
        return False

    def _on_leave_tile(self, *_args):
        try:
            self.get_style_context().remove_class('dccb-tile-hover')
            self.get_style_context().remove_class(self.box_window.css_hover_class)
        except Exception:
            pass
        return False


    def _set_icon(self):
        try:
            if self.path.suffix == '.desktop':
                desktop = Gio.DesktopAppInfo.new_from_filename(str(self.path))
                if desktop and desktop.get_icon():
                    self.image.set_from_gicon(desktop.get_icon(), Gtk.IconSize.DIALOG)
                    self.image.set_pixel_size(self.box_window.settings.get('icon_size', 48))
                    return
            gfile = Gio.File.new_for_path(str(self.path))
            info = gfile.query_info('standard::icon', Gio.FileQueryInfoFlags.NONE, None)
            icon = info.get_icon()
            if icon:
                self.image.set_from_gicon(icon, Gtk.IconSize.DIALOG)
                self.image.set_pixel_size(self.box_window.settings.get('icon_size', 48))
                return
        except Exception:
            pass
        self.image.set_from_icon_name('text-x-generic', Gtk.IconSize.DIALOG)
        self.image.set_pixel_size(self.box_window.settings.get('icon_size', 48))

    def _on_button_press(self, _widget, event):
        if event.button == 1 and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self._cancel_manual_drag()
            open_path(self.path)
            return True
        if event.button == 1:
            self._pressed = True
            self._dragging = False
            self._last_motion_area = None
            self._last_motion_target = None
            self._last_same_box_local = None
            self._last_root = None
            self._press_offset = (int(event.x), int(event.y))
            self._press_root = (int(event.x_root), int(event.y_root))
            self._press_tile_pos = (int(getattr(self, 'pos_x', 0)), int(getattr(self, 'pos_y', 0)))
            try:
                Gtk.grab_add(self)
                self._grabbed = True
            except Exception:
                self._grabbed = False
            if self._drag_timeout:
                GLib.source_remove(self._drag_timeout)
            if self._drag_watchdog:
                GLib.source_remove(self._drag_watchdog)
            self._drag_timeout = GLib.timeout_add(7000, self._force_cancel_manual_drag)
            self._drag_watchdog = GLib.timeout_add(100, self._manual_drag_watchdog)
            return True
        if event.button == 3:
            menu = Gtk.Menu()
            open_item = Gtk.MenuItem(label='Open')
            open_item.connect('activate', lambda *_: open_path(self.path))
            desktop_item = Gtk.MenuItem(label='Move to Desktop')
            desktop_item.connect('activate', lambda *_: self.box_window.move_item_to_desktop(self.path))
            remove_item = Gtk.MenuItem(label='Delete to Trash')
            remove_item.connect('activate', lambda *_: self.box_window.trash_item(self.path))
            menu.append(open_item)
            menu.append(desktop_item)
            menu.append(remove_item)
            menu.show_all()
            menu.popup_at_pointer(event)
            return True
        return False

    def _on_motion(self, _widget, event):
        if not self._pressed:
            return False
        root_x, root_y = int(event.x_root), int(event.y_root)
        start_x, start_y = self._press_root
        if not self._dragging:
            if abs(root_x - start_x) < 4 and abs(root_y - start_y) < 4:
                return True
            self._dragging = True
            try:
                self.get_style_context().add_class('dccb-tile-hover')
                self.get_style_context().add_class(self.box_window.css_hover_class)
                self.set_opacity(0.35)
            except Exception:
                pass

        self._last_root = (root_x, root_y)
        target = self.box_window.app.box_at_root(root_x, root_y, margin=8)
        self._last_motion_target = target
        if target is self.box_window:
            self._last_motion_area = 'same'
            try:
                start_root_x, start_root_y = self._press_root
                start_tile_x, start_tile_y = self._press_tile_pos
                local_x = int(start_tile_x + (root_x - start_root_x))
                local_y = int(start_tile_y + (root_y - start_root_y))
                self._last_same_box_local = (int(local_x), int(local_y))
            except Exception:
                pass
        else:
            self._last_motion_area = 'other' if target is not None else 'outside'
        # Keep the real tile stationary while dragging.  A lightweight preview
        # follows the pointer, and the real tile snaps into place only on release.
        self._update_drag_preview(root_x, root_y)
        return True

    def _on_button_release(self, _widget, event):
        if event.button != 1 or not self._pressed:
            return False
        root_x, root_y = int(event.x_root), int(event.y_root)
        was_dragging = self._dragging
        off_x, off_y = self._press_offset
        last_motion_area = self._last_motion_area
        last_motion_target = self._last_motion_target
        last_same_box_local = self._last_same_box_local
        self._cancel_manual_drag(remove_hover=True)
        if was_dragging:
            tile_w, tile_h = self.get_allocated_width(), self.get_allocated_height()
            target = self.box_window.app.box_for_drag_release(root_x, root_y, off_x, off_y, tile_w, tile_h)

            # Same-box movement must never route through the export path.  Use the
            # last valid same-box local coordinates from pointer motion when final
            # release coordinates are unreliable, then save only the icon position.
            if target is self.box_window or (target is None and last_motion_area == 'same'):
                try:
                    if last_same_box_local is not None:
                        local_x, local_y = last_same_box_local
                    else:
                        start_root_x, start_root_y = self._press_root
                        start_tile_x, start_tile_y = self._press_tile_pos
                        local_x = int(start_tile_x + (root_x - start_root_x))
                        local_y = int(start_tile_y + (root_y - start_root_y))
                    self.box_window.save_icon_position(self.path.name, local_x, local_y, save=True)
                    pos = self.box_window.settings.setdefault('positions', {}).get(self.path.name, {})
                    self.pos_x = int(pos.get('x', local_x))
                    self.pos_y = int(pos.get('y', local_y))
                    try:
                        self.box_window.fixed.move(self, self.pos_x, self.pos_y)
                    except Exception:
                        pass
                except Exception as e:
                    print(f'{APP_ID}: same-box move failed: {e}', file=sys.stderr, flush=True)
                return True

            # If the final event coordinates miss, but the last motion was over a
            # different comment box, transfer into that box instead of exporting.
            if target is None and last_motion_area == 'other' and last_motion_target is not None:
                target = last_motion_target

            if target is not None:
                target.receive_item_from_box(self.box_window, self.path, root_x, root_y, off_x, off_y)
            else:
                # Export only when the released tile is outside every comment box.
                # Pass tile top-left, not pointer center, so Nemo places it where
                # the tile was actually released.
                self.box_window.move_item_to_desktop(self.path, root_x=root_x - off_x, root_y=root_y - off_y)
            return True
        return True

    def _on_grab_broken(self, *_args):
        self._cancel_manual_drag()
        return False

    def _manual_drag_watchdog(self):
        # If GTK misses the button-release event, do not leave a grab active.
        if not self._pressed:
            self._drag_watchdog = None
            return False
        try:
            display = Gdk.Display.get_default()
            seat = display.get_default_seat()
            pointer = seat.get_pointer()
            state = pointer.get_state(self.box_window.get_window())
            mask = state[-1] if isinstance(state, tuple) else 0
            if not (int(mask) & int(Gdk.ModifierType.BUTTON1_MASK)):
                self._cancel_manual_drag()
                self._drag_watchdog = None
                return False
        except Exception:
            pass
        return True

    def _force_cancel_manual_drag(self):
        self._cancel_manual_drag()
        return False

    def _cancel_manual_drag(self, remove_hover=True):
        if self._drag_timeout:
            try:
                GLib.source_remove(self._drag_timeout)
            except Exception:
                pass
            self._drag_timeout = None
        if self._drag_watchdog:
            try:
                GLib.source_remove(self._drag_watchdog)
            except Exception:
                pass
            self._drag_watchdog = None
        self._destroy_drag_preview()
        self._pressed = False
        self._dragging = False
        self._last_motion_area = None
        self._last_motion_target = None
        self._last_same_box_local = None
        self._last_root = None
        if self._grabbed:
            try:
                Gtk.grab_remove(self)
            except Exception:
                pass
            self._grabbed = False
        try:
            self.set_opacity(1.0)
        except Exception:
            pass
        if remove_hover:
            try:
                self.get_style_context().remove_class('dccb-tile-hover')
                self.get_style_context().remove_class(self.box_window.css_hover_class)
            except Exception:
                pass

    def _update_drag_preview(self, root_x, root_y):
        try:
            if self._drag_preview is None:
                size = int(self.box_window.settings.get('icon_size', 48))
                size = max(24, min(96, size))
                pixbuf = self._load_drag_pixbuf(size)

                win = Gtk.Window(type=Gtk.WindowType.POPUP)
                win.set_decorated(False)
                win.set_resizable(False)
                win.set_accept_focus(False)
                win.set_focus_on_map(False)
                win.set_skip_taskbar_hint(True)
                win.set_skip_pager_hint(True)
                try:
                    win.set_type_hint(Gdk.WindowTypeHint.DND)
                    win.set_keep_above(True)
                    win.set_opacity(0.86)
                except Exception:
                    pass

                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                box.set_margin_top(4)
                box.set_margin_bottom(4)
                box.set_margin_start(4)
                box.set_margin_end(4)

                image = Gtk.Image()
                if pixbuf:
                    image.set_from_pixbuf(pixbuf)
                else:
                    image.set_from_icon_name('text-x-generic', Gtk.IconSize.DIALOG)
                    image.set_pixel_size(size)
                box.pack_start(image, False, False, 0)

                label = Gtk.Label(label=self.path.name)
                label.set_ellipsize(Pango.EllipsizeMode.END)
                label.set_max_width_chars(12)
                label.set_lines(1)
                box.pack_start(label, False, False, 0)

                win.add(box)
                win.show_all()
                self._drag_preview = win

            self._drag_preview.move(int(root_x) + 10, int(root_y) + 10)
        except Exception:
            self._destroy_drag_preview()

    def _destroy_drag_preview(self):
        preview = self._drag_preview
        self._drag_preview = None
        if preview is not None:
            try:
                preview.destroy()
            except Exception:
                pass


    def _load_drag_pixbuf(self, size: int = 48):
        theme = Gtk.IconTheme.get_default()

        def load_icon_name(name):
            try:
                return theme.load_icon(name, size, Gtk.IconLookupFlags.FORCE_SIZE)
            except Exception:
                return None

        try:
            if self.path.is_file():
                content = Gio.content_type_guess(str(self.path), None)[0]
                if content and content.startswith('image/'):
                    return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(self.path), size, size, True)
        except Exception:
            pass

        try:
            if self.path.suffix == '.desktop':
                desktop = Gio.DesktopAppInfo.new_from_filename(str(self.path))
                icon = desktop.get_icon() if desktop else None
                if icon:
                    info = theme.lookup_by_gicon(icon, size, Gtk.IconLookupFlags.FORCE_SIZE)
                    if info:
                        return info.load_icon()
        except Exception:
            pass

        try:
            gfile = Gio.File.new_for_path(str(self.path))
            info = gfile.query_info('standard::icon', Gio.FileQueryInfoFlags.NONE, None)
            icon = info.get_icon()
            if icon:
                icon_info = theme.lookup_by_gicon(icon, size, Gtk.IconLookupFlags.FORCE_SIZE)
                if icon_info:
                    return icon_info.load_icon()
        except Exception:
            pass

        if self.path.is_dir():
            return load_icon_name('folder')
        return load_icon_name('text-x-generic') or load_icon_name('unknown')

    def _on_drag_begin(self, _widget, context):
        size = int(self.box_window.settings.get('icon_size', 48))
        size = max(24, min(128, size))
        pixbuf = self._load_drag_pixbuf(size)
        if pixbuf:
            try:
                Gtk.drag_set_icon_pixbuf(context, pixbuf, size // 2, size // 2)
            except Exception:
                try:
                    self.drag_source_set_icon_pixbuf(pixbuf)
                except Exception:
                    pass

    def _on_drag_data_get(self, _widget, _context, data, _info, _time):
        data.set_uris([self.path.as_uri()])

    def _on_drag_data_delete(self, *_args):
        # Do not delete the source if the URI was dropped back inside a comment box to reposition it.
        try:
            key = str(self.path.resolve())
        except Exception:
            key = str(self.path)
        if key in self.box_window.app.internal_position_drops:
            self.box_window.app.internal_position_drops.discard(key)
            self.box_window.refresh_later()
            return
        try:
            if self.path.exists():
                if self.path.is_dir():
                    shutil.rmtree(self.path)
                else:
                    self.path.unlink()
        except Exception:
            pass
        self.box_window.settings.setdefault('positions', {}).pop(self.path.name, None)
        self.box_window.refresh_later()


class DesktopBoxWindow(Gtk.Window):
    def __init__(self, app, settings):
        super().__init__(title=settings.get('title', 'Desktop Comment Box'))
        self._setup_transparent_window()
        self.app = app
        self.settings = settings
        self.settings.setdefault('positions', {})
        self.box_id = settings['id']
        safe_id = ''.join(ch if ch.isalnum() else '-' for ch in str(self.box_id))[:32]
        self.css_box_class = f'dccb-box-{safe_id}'
        self.css_titlebar_class = f'dccb-titlebar-{safe_id}'
        self.css_title_class = f'dccb-title-{safe_id}'
        self.css_label_class = f'dccb-label-{safe_id}'
        self.css_hover_class = f'dccb-hover-{safe_id}'
        self.folder = Path(settings['folder']).expanduser()
        self.folder.mkdir(parents=True, exist_ok=True)
        self._configure_timer = None
        self._refresh_timer = None
        self._folder_monitor = None
        self._suppress_config = False
        self._tiles = {}

        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_below(True)
        self.stick()
        self.set_app_paintable(True)
        self.connect('draw', self._on_draw_transparent)
        w, h = clamp_size(settings.get('width', DEFAULTS['width']), settings.get('height', DEFAULTS['height']))
        self.set_default_size(w, h)
        self.set_resizable(True)
        self.set_size_request(MIN_BOX_WIDTH, MIN_BOX_HEIGHT)
        # Advertise both the minimum and hidden maximum to the window manager so
        # the resize preview stops at the cap instead of snapping back after release.
        # The icon canvas no longer requests the current box size, so max hints do
        # not lock resizing like they did in v1.2.1.
        try:
            geometry = Gdk.Geometry()
            geometry.min_width = MIN_BOX_WIDTH
            geometry.min_height = MIN_BOX_HEIGHT
            geometry.max_width = MAX_BOX_WIDTH
            geometry.max_height = MAX_BOX_HEIGHT
            self.set_geometry_hints(None, geometry, Gdk.WindowHints.MIN_SIZE | Gdk.WindowHints.MAX_SIZE)
        except Exception:
            pass
        try:
            self.set_opacity(max(0.05, min(1.0, float(settings.get('window_opacity', DEFAULTS['window_opacity'])))))
        except Exception:
            pass
        self.move(int(settings.get('x', DEFAULTS['x'])), int(settings.get('y', DEFAULTS['y'])))
        self.connect('configure-event', self._on_configure)
        self.connect('delete-event', self._on_delete)

        self._build_ui()
        self._apply_css()
        self._setup_monitor()
        self.refresh_icons()
        self.add_drop_target(self)
        self.show_all()

    def _setup_transparent_window(self):
        try:
            screen = self.get_screen()
            visual = screen.get_rgba_visual()
            if visual:
                self.set_visual(visual)
        except Exception:
            pass
        try:
            self.get_style_context().add_class('dccb-window')
        except Exception:
            pass

    def _on_draw_transparent(self, _widget, cr):
        if cairo is not None:
            try:
                cr.set_operator(cairo.OPERATOR_SOURCE)
                cr.set_source_rgba(0, 0, 0, 0)
                cr.paint()
                cr.set_operator(cairo.OPERATOR_OVER)
            except Exception:
                pass
        return False

    def _build_ui(self):
        self.grid = Gtk.Grid()
        self.grid.get_style_context().add_class('dccb-grid')
        self.grid.set_row_homogeneous(False)
        self.grid.set_column_homogeneous(False)
        self.add(self.grid)

        self._add_resize_grip(0, 0, Gdk.WindowEdge.NORTH_WEST, 'nw-resize')
        self._add_resize_grip(1, 0, Gdk.WindowEdge.NORTH, 'n-resize')
        self._add_resize_grip(2, 0, Gdk.WindowEdge.NORTH_EAST, 'ne-resize')
        self._add_resize_grip(0, 1, Gdk.WindowEdge.WEST, 'w-resize')
        self._add_resize_grip(2, 1, Gdk.WindowEdge.EAST, 'e-resize')
        self._add_resize_grip(0, 2, Gdk.WindowEdge.SOUTH_WEST, 'sw-resize')
        self._add_resize_grip(1, 2, Gdk.WindowEdge.SOUTH, 's-resize')
        self._add_resize_grip(2, 2, Gdk.WindowEdge.SOUTH_EAST, 'se-resize')

        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.outer.get_style_context().add_class('dccb-box')
        self.outer.get_style_context().add_class(self.css_box_class)
        self.grid.attach(self.outer, 1, 1, 1, 1)

        self.title_bar = Gtk.EventBox()
        self.title_bar.get_style_context().add_class('dccb-titlebar')
        self.title_bar.get_style_context().add_class(self.css_titlebar_class)
        self.title_bar.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.title_bar.connect('button-press-event', self._on_title_press)
        self.outer.pack_start(self.title_bar, False, False, 0)

        self.title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.title_row.set_margin_start(10)
        self.title_row.set_margin_end(8)
        self.title_row.set_margin_top(6)
        self.title_row.set_margin_bottom(6)
        self.title_bar.add(self.title_row)

        self.title_label = Gtk.Label(label=self.settings.get('title', 'My Icons'))
        self.title_label.set_xalign(0.0)
        self.title_label.get_style_context().add_class('dccb-title')
        self.title_label.get_style_context().add_class(self.css_title_class)
        self.title_row.pack_start(self.title_label, True, True, 0)

        self.menu_button = Gtk.Button.new_from_icon_name('open-menu-symbolic', Gtk.IconSize.MENU)
        self.menu_button.set_relief(Gtk.ReliefStyle.NONE)
        self.menu_button.connect('clicked', self._show_menu)
        self.title_row.pack_end(self.menu_button, False, False, 0)

        self.viewport = Gtk.EventBox()
        self.viewport.set_visible_window(False)
        self.viewport.set_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.outer.pack_start(self.viewport, True, True, 0)

        self.fixed = Gtk.Layout()
        self.fixed.get_style_context().add_class('dccb-canvas')
        self.fixed.set_hexpand(True)
        self.fixed.set_vexpand(True)
        self.fixed.set_size_request(1, 1)
        self.fixed.set_margin_top(8)
        self.fixed.set_margin_bottom(8)
        self.fixed.set_margin_start(8)
        self.fixed.set_margin_end(8)
        self.viewport.add(self.fixed)

        self.add_drop_target(self.outer)
        self.add_drop_target(self.title_bar)
        self.add_drop_target(self.viewport)
        self.add_drop_target(self.fixed)

    def _add_resize_grip(self, col, row, edge, cursor_name):
        grip = Gtk.EventBox()
        grip.get_style_context().add_class('dccb-resize-grip')
        grip.set_visible_window(False)
        grip.set_size_request(8, 8)
        grip.connect('button-press-event', self._on_resize_press, edge)
        grip.connect('enter-notify-event', self._on_grip_enter, cursor_name)
        grip.connect('leave-notify-event', self._on_grip_leave)
        grip.set_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.grid.attach(grip, col, row, 1, 1)
        if row == 1:
            grip.set_vexpand(True)
        if col == 1:
            grip.set_hexpand(True)

    def _on_grip_enter(self, widget, _event, cursor_name):
        win = widget.get_window()
        if win:
            display = Gdk.Display.get_default()
            win.set_cursor(Gdk.Cursor.new_from_name(display, cursor_name))
        return False

    def _on_grip_leave(self, widget, _event):
        win = widget.get_window()
        if win:
            win.set_cursor(None)
        return False

    def _on_resize_press(self, _widget, event, edge):
        if event.button != 1:
            return False
        gdk_window = self.get_window()
        if gdk_window:
            gdk_window.begin_resize_drag(edge, event.button, int(event.x_root), int(event.y_root), event.time)
        return True

    def _on_title_press(self, _widget, event):
        if event.button == 1 and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self.rename_dialog()
            return True
        if event.button == 1:
            gdk_window = self.get_window()
            if gdk_window:
                gdk_window.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
            return True
        if event.button == 3:
            self._show_menu(None, event)
            return True
        return False

    def _show_menu(self, _button=None, event=None):
        menu = Gtk.Menu()
        items = [
            ('Rename', lambda *_: self.rename_dialog()),
            ('Configure Appearance', lambda *_: self.configure_dialog()),
            ('Open Group Folder', lambda *_: open_path(self.folder)),
            ('Reset Icon Positions', lambda *_: self.reset_icon_positions()),
            ('New Box', lambda *_: self.app.add_box()),
            ('Remove This Box', lambda *_: self.confirm_remove()),
            ('Quit App', lambda *_: self.app.quit()),
        ]
        for label, cb in items:
            item = Gtk.MenuItem(label=label)
            item.connect('activate', cb)
            menu.append(item)
        menu.show_all()
        if event:
            menu.popup_at_pointer(event)
        else:
            menu.popup_at_widget(self.menu_button, Gdk.Gravity.SOUTH_EAST, Gdk.Gravity.NORTH_EAST, None)

    def _apply_css(self):
        css = f'''
        window.dccb-window, .dccb-window, .dccb-grid, .dccb-resize-grip, .dccb-canvas {{
            background-color: transparent;
            background-image: none;
            box-shadow: none;
            border: none;
        }}
        .dccb-box.{self.css_box_class} {{
            background-color: {rgba_css(self.settings.get('background'), DEFAULTS['background'])};
            border: 2px solid {rgba_css(self.settings.get('border'), DEFAULTS['border'])};
            border-radius: 12px;
        }}
        .dccb-titlebar.{self.css_titlebar_class} {{
            background-color: rgba(255,255,255,0.05);
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
        }}
        .dccb-titlebar.{self.css_titlebar_class} button, .dccb-titlebar.{self.css_titlebar_class} button:hover, .dccb-titlebar.{self.css_titlebar_class} button:active {{
            background-color: transparent;
            background-image: none;
            border: none;
            box-shadow: none;
        }}
        .dccb-title.{self.css_title_class} {{
            color: {rgba_css(self.settings.get('title_color'), DEFAULTS['title_color'])};
            font-weight: bold;
            font-size: 13pt;
        }}
        .dccb-icon-label.{self.css_label_class} {{
            color: {rgba_css(self.settings.get('label_color'), DEFAULTS['label_color'])};
        }}
        .dccb-tile-hover.{self.css_hover_class} {{
            background-color: {rgba_css(self.settings.get('hover'), DEFAULTS['hover'])};
            border-radius: 8px;
        }}
        '''
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _setup_monitor(self):
        try:
            gfile = Gio.File.new_for_path(str(self.folder))
            self._folder_monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._folder_monitor.connect('changed', lambda *_: self.refresh_later())
        except Exception:
            self._folder_monitor = None

    def add_drop_target(self, widget):
        try:
            widget.drag_dest_set(Gtk.DestDefaults.ALL, URI_TARGETS, Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
            widget.connect('drag-motion', self._on_drag_motion)
            widget.connect('drag-drop', self._on_drag_drop)
            widget.connect('drag-data-received', self._on_drag_data_received)
        except Exception:
            pass

    def _on_drag_motion(self, _widget, context, _x, _y, time):
        try:
            context.drag_status(Gdk.DragAction.MOVE, time)
        except Exception:
            pass
        return True

    def _on_drag_drop(self, widget, context, x, y, time):
        try:
            self._last_drop_widget = widget
            self._last_drop_xy = (int(x), int(y))
            widget.drag_get_data(context, Gdk.Atom.intern('text/uri-list', False), time)
            return True
        except Exception:
            return False

    def _drop_coords_in_fixed(self, widget, x, y):
        try:
            if widget is self.fixed:
                return int(x), int(y)
            # Convert drop coordinates from widget space to root, then to fixed space.
            wox, woy = gdk_origin_xy(widget.get_window())
            fox, foy = gdk_origin_xy(self.fixed.get_window())
            return int(wox + x - fox), int(woy + y - foy)
        except Exception:
            pass
        try:
            # Fallback to current pointer position.
            display = Gdk.Display.get_default()
            seat = display.get_default_seat()
            pointer = seat.get_pointer()
            _screen, rx, ry = pointer.get_position()
            fox, foy = gdk_origin_xy(self.fixed.get_window())
            return int(rx - fox), int(ry - foy)
        except Exception:
            return self.next_free_position()

    def _on_drag_data_received(self, widget, context, x, y, data, _info, time):
        moved_any = False
        drop_x, drop_y = self._drop_coords_in_fixed(widget, x, y)
        try:
            uris = list(data.get_uris() or [])
            offset = 0
            for uri in uris:
                src = uri_to_path(uri)
                if not src or not src.exists():
                    continue
                try:
                    src_resolved = src.resolve()
                    folder_resolved = self.folder.resolve()
                    if src_resolved == folder_resolved or folder_resolved in src_resolved.parents:
                        # Same-box drop: this is a position change, not a file move.
                        self.save_icon_position(src.name, drop_x + offset, drop_y + offset, save=False)
                        self.app.internal_position_drops.add(str(src_resolved))
                        GLib.timeout_add(2000, self._clear_internal_position_drop, str(src_resolved))
                        offset += 22
                        moved_any = True
                        continue
                except Exception:
                    pass
                old_name = src.name
                dest = move_path_to(src, self.folder)
                self.settings.setdefault('positions', {}).pop(old_name, None)
                self.save_icon_position(dest.name, drop_x + offset, drop_y + offset, save=False)
                offset += 22
                moved_any = True
        except Exception as e:
            print(f'{APP_ID}: drop failed: {e}', file=sys.stderr, flush=True)
        try:
            Gtk.drag_finish(context, moved_any, False, time)
        except Exception:
            pass
        if moved_any:
            self.app.save()
            self.refresh_icons()
        return True


    def _clear_internal_position_drop(self, key):
        try:
            self.app.internal_position_drops.discard(key)
        except Exception:
            pass
        return False

    def refresh_later(self):
        if self._refresh_timer:
            return
        self._refresh_timer = GLib.timeout_add(250, self._refresh_now)

    def _refresh_now(self):
        self._refresh_timer = None
        self.refresh_icons()
        return False

    def _visible_entries(self):
        show_hidden = bool(self.settings.get('show_hidden', False))
        try:
            return sorted([p for p in self.folder.iterdir() if show_hidden or not p.name.startswith('.')], key=lambda p: p.name.lower())
        except Exception:
            return []

    def refresh_icons(self):
        for child in list(self.fixed.get_children()):
            self.fixed.remove(child)
        self._tiles = {}

        entries = self._visible_entries()
        live_names = {p.name for p in entries}
        positions = self.settings.setdefault('positions', {})
        for name in list(positions.keys()):
            if name not in live_names:
                positions.pop(name, None)

        for path in entries:
            if not isinstance(positions.get(path.name), dict):
                x, y = self.next_free_position()
                positions[path.name] = {'x': x, 'y': y}
            else:
                x = int(positions[path.name].get('x', GRID_MARGIN_X))
                y = int(positions[path.name].get('y', GRID_MARGIN_Y))
            x, y = self.snap_position(x, y, exclude_name=path.name)
            positions[path.name] = {'x': x, 'y': y}
            tile = IconTile(self, path, x, y)
            self.fixed.put(tile, x, y)
            self._tiles[path.name] = tile
        self._resize_canvas_to_fit()
        self.fixed.show_all()
        self.save_later()

    def _tile_step(self):
        return tile_step_for_settings(self.settings)

    def next_free_position(self):
        step_x, step_y = self._tile_step()
        used = set()
        for pos in self.settings.setdefault('positions', {}).values():
            if isinstance(pos, dict):
                gx = round(int(pos.get('x', 8)) / step_x)
                gy = round(int(pos.get('y', 8)) / step_y)
                used.add((gx, gy))
        width = max(1, int(self.settings.get('width', DEFAULTS['width'])) - 32)
        cols = max(1, width // step_x)
        for n in range(0, 10000):
            cell = (n % cols, n // cols)
            if cell not in used:
                return grid_cell_to_xy(self.settings, cell[0], cell[1])
        return GRID_MARGIN_X, GRID_MARGIN_Y

    def clamp_position(self, x, y):
        return clamp_position_for_settings(self.settings, x, y)

    def _occupied_cells(self, exclude_name=None):
        occupied = set()
        positions = self.settings.setdefault('positions', {})
        for name, pos in positions.items():
            if name == exclude_name or not isinstance(pos, dict):
                continue
            try:
                occupied.add(xy_to_grid_cell(self.settings, int(pos.get('x', GRID_MARGIN_X)), int(pos.get('y', GRID_MARGIN_Y))))
            except Exception:
                pass
        return occupied

    def snap_position(self, x, y, exclude_name=None):
        base = xy_to_grid_cell(self.settings, x, y)
        occupied = self._occupied_cells(exclude_name=exclude_name)
        if base not in occupied:
            return grid_cell_to_xy(self.settings, *base)
        # Find the nearest open grid cell, like a desktop icon grid would.
        canvas_w, canvas_h = canvas_size_for_settings(self.settings)
        step_x, step_y = self._tile_step()
        icon = int(self.settings.get('icon_size', DEFAULTS['icon_size']))
        tile_w = max(80, icon + 38)
        tile_h = max(82, icon + 54)
        max_gx = max(0, (canvas_w - tile_w - GRID_MARGIN_X) // step_x)
        max_gy = max(0, (canvas_h - tile_h - GRID_MARGIN_Y) // step_y)
        bx, by = base
        best = None
        best_score = None
        for gy in range(0, int(max_gy) + 1):
            for gx in range(0, int(max_gx) + 1):
                if (gx, gy) in occupied:
                    continue
                score = abs(gx - bx) + abs(gy - by)
                if best is None or score < best_score:
                    best = (gx, gy)
                    best_score = score
        if best is None:
            best = base
        return grid_cell_to_xy(self.settings, *best)

    def move_tile(self, tile: IconTile, x, y):
        x, y = self.snap_position(x, y, exclude_name=tile.path.name)
        old_x, old_y = int(getattr(tile, 'pos_x', x)), int(getattr(tile, 'pos_y', y))
        if x == old_x and y == old_y:
            return
        tile.pos_x = x
        tile.pos_y = y
        try:
            # Gtk.Fixed/Layout will invalidate the old and new child regions.
            # Avoid queueing redraws for the whole viewport/window on every
            # pointer-motion event; that was the main source of interaction lag.
            self.fixed.move(tile, x, y)
        except Exception:
            pass

    def save_icon_position(self, name, x, y, save=True):
        x, y = self.snap_position(x, y, exclude_name=name)
        self.settings.setdefault('positions', {})[name] = {'x': int(x), 'y': int(y)}
        if save:
            self.app.save()

    def _resize_canvas_to_fit(self):
        # The icon canvas must NOT request the saved box size as its minimum size.
        # Doing that made v1.2.1 feel locked.  Keep the request tiny and set only
        # the Layout's virtual canvas size; the window allocation controls the
        # visible clipped area.
        try:
            width, height = clamp_size(self.settings.get('width', DEFAULTS['width']), self.settings.get('height', DEFAULTS['height']))
            canvas_w = max(100, width - 32)
            canvas_h = max(80, height - 62)
            # Keep requests tiny.  Gtk.Layout.set_size() changes the virtual
            # canvas requisition; tying that to the current window size caused a
            # feedback loop where moving/resizing the box could make it grow.
            self.fixed.set_size_request(1, 1)
            self.viewport.set_size_request(1, 1)
        except Exception:
            pass

    def root_rect_candidates(self):
        """Return possible root-coordinate rectangles for this box.

        Different Mint/Cinnamon/GTK paths can report slightly different top-left
        coordinates for borderless keep-below windows.  Box-to-box dragging needs
        target detection to be more forgiving than one single coordinate source,
        so use the live Gdk origin, Gtk window position, and saved config position.
        """
        rects = []
        try:
            width, height = self.get_size()
            width = int(width)
            height = int(height)
        except Exception:
            width = int(self.settings.get('width', DEFAULTS['width']))
            height = int(self.settings.get('height', DEFAULTS['height']))

        def add_rect(x, y):
            try:
                rect = (int(x), int(y), width, height)
                if rect not in rects:
                    rects.append(rect)
            except Exception:
                pass

        try:
            add_rect(*gdk_origin_xy(self.get_window()))
        except Exception:
            pass
        try:
            add_rect(*self.get_position())
        except Exception:
            pass
        try:
            add_rect(self.settings.get('x', DEFAULTS['x']), self.settings.get('y', DEFAULTS['y']))
        except Exception:
            pass
        return rects

    def root_point_inside(self, root_x, root_y, margin=0):
        try:
            rx = int(root_x)
            ry = int(root_y)
            m = int(margin or 0)
            for ox, oy, width, height in self.root_rect_candidates():
                if (ox - m) <= rx <= (ox + int(width) + m) and (oy - m) <= ry <= (oy + int(height) + m):
                    return True
        except Exception:
            pass
        return False

    def root_overlap_area(self, left, top, width, height, margin=0):
        try:
            left = int(left)
            top = int(top)
            right = left + int(width)
            bottom = top + int(height)
            m = int(margin or 0)
            best = 0
            for ox, oy, ow, oh in self.root_rect_candidates():
                rx1 = int(ox) - m
                ry1 = int(oy) - m
                rx2 = int(ox) + int(ow) + m
                ry2 = int(oy) + int(oh) + m
                ix = max(0, min(right, rx2) - max(left, rx1))
                iy = max(0, min(bottom, ry2) - max(top, ry1))
                best = max(best, ix * iy)
            return best
        except Exception:
            return 0

    def _fixed_offset_in_window(self):
        """Return the fixed icon canvas origin relative to this window.

        On some Cinnamon/Muffin setups, the child GdkWindow origin can report a
        stale or zero root position for borderless keep-below windows.  Using the
        fixed widget's offset inside the window and combining it with the window
        root rectangle is more stable for same-box and box-to-box icon drops.
        """
        candidates = []
        try:
            coords = self.fixed.translate_coordinates(self, 0, 0)
            if coords:
                candidates.append((int(coords[0]), int(coords[1])))
        except Exception:
            pass
        try:
            fx = int(self.fixed.get_allocation().x)
            fy = int(self.fixed.get_allocation().y)
            vx = int(self.viewport.get_allocation().x)
            vy = int(self.viewport.get_allocation().y)
            ox = int(self.outer.get_allocation().x)
            oy = int(self.outer.get_allocation().y)
            candidates.append((ox + vx + fx, oy + vy + fy))
        except Exception:
            pass
        # Typical fallback: 8px resize border + title bar row + 8px canvas margin.
        candidates.append((16, TITLEBAR_CAPTURE_OFFSET + 8))
        for x, y in candidates:
            if -50 <= x <= MAX_BOX_WIDTH and -50 <= y <= MAX_BOX_HEIGHT:
                return x, y
        return 16, TITLEBAR_CAPTURE_OFFSET + 8

    def root_to_fixed(self, root_x, root_y, off_x=0, off_y=0):
        """Convert root pointer coordinates to this box's icon-canvas coordinates.

        The old implementation used only self.fixed.get_window()'s root origin.
        On some setups that origin is wrong, causing drops to clamp to the far
        right or upper-right grid cell.  This version tests every available box
        origin candidate and chooses the one that places the drop inside/nearest
        the current canvas.
        """
        try:
            rx = int(root_x)
            ry = int(root_y)
            ox_rel, oy_rel = self._fixed_offset_in_window()
            canvas_w, canvas_h = canvas_size_for_settings(self.settings)
            best = None
            best_score = None
            for wx, wy, _ww, _hh in self.root_rect_candidates():
                lx = int(rx - int(wx) - ox_rel - int(off_x))
                ly = int(ry - int(wy) - oy_rel - int(off_y))
                dx = 0 if 0 <= lx <= canvas_w else min(abs(lx), abs(lx - canvas_w))
                dy = 0 if 0 <= ly <= canvas_h else min(abs(ly), abs(ly - canvas_h))
                score = dx + dy
                if best is None or score < best_score:
                    best = (lx, ly)
                    best_score = score
            if best is not None:
                return best
        except Exception:
            pass
        try:
            fox, foy = gdk_origin_xy(self.fixed.get_window())
            return int(root_x) - int(fox) - int(off_x), int(root_y) - int(foy) - int(off_y)
        except Exception:
            return self.next_free_position()

    def receive_item_from_box(self, source_window, path: Path, root_x, root_y, off_x=0, off_y=0):
        local_x, local_y = self.root_to_fixed(root_x, root_y, off_x, off_y)
        if source_window is self:
            self.save_icon_position(path.name, local_x, local_y, save=True)
            tile = self._tiles.get(path.name)
            if tile:
                try:
                    pos = self.settings.setdefault('positions', {}).get(path.name, {})
                    self.move_tile(tile, int(pos.get('x', local_x)), int(pos.get('y', local_y)))
                except Exception:
                    pass
            return

        old_name = path.name
        try:
            dest = move_path_to(path, self.folder)
        except Exception as e:
            print(f'{APP_ID}: move between boxes failed: {e}', file=sys.stderr, flush=True)
            return
        try:
            source_window.settings.setdefault('positions', {}).pop(old_name, None)
            source_window.refresh_later()
        except Exception:
            pass
        self.save_icon_position(dest.name, local_x, local_y, save=False)
        self.app.save()
        self.refresh_later()

    def reset_icon_positions(self):
        self.settings['positions'] = {}
        self.app.save()
        self.refresh_icons()

    def _on_configure(self, _widget, event):
        if self._suppress_config:
            return False
        self.settings['x'] = int(event.x)
        self.settings['y'] = int(event.y)
        w, h = clamp_size(event.width, event.height)
        self.settings['width'] = w
        self.settings['height'] = h
        # Most window managers obey the max geometry hints and show the cap live.
        # If one reports an out-of-range size anyway, clamp after the drag settles
        # instead of fighting the live resize and snapping back to the old size.
        if int(event.width) > MAX_BOX_WIDTH or int(event.height) > MAX_BOX_HEIGHT:
            GLib.timeout_add(120, self._enforce_max_size, w, h)
        self._resize_canvas_to_fit()
        self.save_later()
        return False

    def _enforce_max_size(self, width, height):
        try:
            self._suppress_config = True
            self.resize(int(width), int(height))
        except Exception:
            pass
        finally:
            self._suppress_config = False
        return False

    def save_later(self):
        if self._configure_timer:
            GLib.source_remove(self._configure_timer)
        self._configure_timer = GLib.timeout_add(800, self._save_now)

    def _save_now(self):
        self._configure_timer = None
        self.app.save()
        return False

    def rename_dialog(self):
        dialog = Gtk.Dialog(title='Rename Box', transient_for=self, flags=Gtk.DialogFlags.MODAL)
        dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
        dialog.add_button('Save', Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        entry = Gtk.Entry()
        entry.set_text(self.settings.get('title', 'My Icons'))
        entry.set_activates_default(True)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.add(entry)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            title = entry.get_text().strip() or 'My Icons'
            self.settings['title'] = title
            self.title_label.set_text(title)
            self.set_title(title)
            self.app.save()
        dialog.destroy()

    def configure_dialog(self):
        self._appearance_dialog(self.settings, 'Configure Desktop Comment Box', apply_current=True)

    def configure_defaults_dialog(self):
        defaults = self.app.config.setdefault('defaults', new_default_settings())
        self._appearance_dialog(defaults, 'Configure Default Appearance', apply_current=False)

    def _appearance_dialog(self, target_settings, title, apply_current):
        dialog = Gtk.Dialog(title=title, transient_for=self, flags=Gtk.DialogFlags.MODAL)
        dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
        dialog.add_button('Save', Gtk.ResponseType.OK)
        area = dialog.get_content_area()
        area.set_margin_top(12)
        area.set_margin_bottom(12)
        area.set_margin_start(12)
        area.set_margin_end(12)
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        area.add(grid)

        fields = {}
        color_keys = [
            ('background', 'Background'),
            ('border', 'Border'),
            ('title_color', 'Title text'),
            ('label_color', 'Icon labels'),
            ('hover', 'Hover highlight'),
        ]
        grid.attach(Gtk.Label(label='Color', xalign=0), 1, 0, 1, 1)
        grid.attach(Gtk.Label(label='Opacity', xalign=0), 2, 0, 1, 1)
        for idx, (key, label) in enumerate(color_keys, start=1):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, idx, 1, 1)
            btn = Gtk.ColorButton()
            btn.set_use_alpha(False)
            rgba = Gdk.RGBA()
            rgba.parse(target_settings.get(key, DEFAULTS.get(key, '#ffffffff')))
            btn.set_rgba(rgba)
            opacity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            opacity.set_size_request(130, -1)
            opacity.set_value(round(max(0, min(1, rgba.alpha)) * 100))
            opacity.set_draw_value(True)
            grid.attach(btn, 1, idx, 1, 1)
            grid.attach(opacity, 2, idx, 1, 1)
            fields[key] = (btn, opacity)

        row = len(color_keys) + 1
        grid.attach(Gtk.Label(label='Whole box opacity', xalign=0), 0, row, 1, 1)
        window_opacity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 1)
        window_opacity.set_size_request(180, -1)
        window_opacity.set_value(round(max(0.05, min(1, float(target_settings.get('window_opacity', DEFAULTS['window_opacity'])))) * 100))
        window_opacity.set_draw_value(True)
        grid.attach(window_opacity, 1, row, 2, 1)
        fields['window_opacity'] = window_opacity

        row += 1
        grid.attach(Gtk.Label(label='Icon size', xalign=0), 0, row, 1, 1)
        spin = Gtk.SpinButton.new_with_range(24, 128, 2)
        spin.set_value(int(target_settings.get('icon_size', 48)))
        grid.attach(spin, 1, row, 2, 1)
        fields['icon_size'] = spin

        row += 1
        hidden = Gtk.CheckButton(label='Show hidden files')
        hidden.set_active(bool(target_settings.get('show_hidden', False)))
        grid.attach(hidden, 0, row, 3, 1)
        fields['show_hidden'] = hidden

        row += 1
        save_as_defaults = None
        if apply_current:
            save_as_defaults = Gtk.CheckButton(label='Use this appearance as defaults for new boxes')
            save_as_defaults.set_tooltip_text("This saves this box's colors, opacity, icon size, and size as the default for newly created boxes.")
            grid.attach(save_as_defaults, 0, row, 3, 1)
        else:
            note = Gtk.Label(label='Defaults only affect boxes created after saving them.')
            note.set_xalign(0)
            note.set_line_wrap(True)
            grid.attach(note, 0, row, 3, 1)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            for key, pair in fields.items():
                if isinstance(pair, tuple):
                    btn, opacity = pair
                    rgba = btn.get_rgba()
                    rgba.alpha = max(0, min(1, opacity.get_value() / 100.0))
                    target_settings[key] = rgba.to_string()
            target_settings['window_opacity'] = max(0.05, min(1.0, fields['window_opacity'].get_value() / 100.0))
            target_settings['icon_size'] = int(fields['icon_size'].get_value())
            target_settings['show_hidden'] = fields['show_hidden'].get_active()
            self.app.save()
            if apply_current:
                try:
                    self.set_opacity(float(self.settings.get('window_opacity', DEFAULTS['window_opacity'])))
                except Exception:
                    pass
                self._apply_css()
                self.refresh_icons()
                try:
                    if save_as_defaults is not None and save_as_defaults.get_active():
                        self.app.copy_defaults_from_box(self.settings)
                except Exception:
                    pass
        dialog.destroy()


    def move_item_to_desktop(self, path: Path, root_x=None, root_y=None):
        try:
            self.settings.setdefault('positions', {}).pop(path.name, None)
            dest = move_path_to(path, DESKTOP_DIR)
            if root_x is not None and root_y is not None:
                set_nemo_icon_position(dest, root_x, root_y, self.settings.get('icon_size', DEFAULTS['icon_size']))
            self.app.save()
        except Exception as e:
            print(f'{APP_ID}: move to desktop failed: {e}', file=sys.stderr, flush=True)
        self.refresh_later()

    def trash_item(self, path: Path):
        try:
            self.settings.setdefault('positions', {}).pop(path.name, None)
            gfile = Gio.File.new_for_path(str(path))
            gfile.trash(None)
        except Exception:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except Exception:
                pass
        self.app.save()
        self.refresh_later()

    def confirm_remove(self):
        dialog = Gtk.MessageDialog(transient_for=self, flags=Gtk.DialogFlags.MODAL, message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.CANCEL, text='Remove this box?')
        dialog.format_secondary_text('All files inside this box will be moved back to the Desktop. The box folder will be deleted.')
        dialog.add_button('Remove Box', Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.app.remove_box(self.box_id)

    def _on_delete(self, *_args):
        self.hide()
        return True

    def destroy_window_only(self):
        try:
            if self._folder_monitor:
                self._folder_monitor.cancel()
        except Exception:
            pass
        self.destroy()


class DesktopCommentBoxApp:
    def __init__(self, create_initial=True):
        ensure_dirs()
        self.lock_handle = open(LOCK_FILE, 'w')
        try:
            fcntl.lockf(self.lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print('Desktop Comment Box is already running. If it is not visible, run: pkill -f desktop_comment_box.py', file=sys.stderr)
            sys.exit(0)
        self.config = load_config(create_initial=create_initial)
        self.windows = {}
        self.internal_position_drops = set()
        self._server_socket = None
        self._server_thread = None
        self._server_running = False
        atexit.register(self._cleanup_control_socket)

    def run(self):
        self._start_control_server()
        self._cleanup_old_drop_launchers()
        if self.config.pop('_repaired_at_start', False):
            self.save()
        if not self.config.get('boxes'):
            print('Desktop Comment Box has no boxes. Run: desktop-comment-box --new', file=sys.stderr)
            return
        for settings in list(self.config.get('boxes', [])):
            settings.setdefault('positions', {})
            self._create_window(settings)
        self.save()
        Gtk.main()

    def _start_control_server(self):
        """Create a small UNIX-socket controller for secondary commands.

        The app intentionally supports exactly one controller process.  A later
        `desktop-comment-box --new` command connects here, asks this running
        process to create one box, then exits instead of opening a second synced
        set of windows.
        """
        try:
            CONTROL_SOCKET.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(CONTROL_SOCKET))
            srv.listen(8)
            srv.settimeout(0.5)
            self._server_socket = srv
            self._server_running = True
            self._server_thread = threading.Thread(target=self._control_server_loop, daemon=True)
            self._server_thread.start()
        except Exception as e:
            print(f'{APP_ID}: control socket disabled: {e}', file=sys.stderr, flush=True)

    def _control_server_loop(self):
        while self._server_running:
            try:
                conn, _addr = self._server_socket.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            with conn:
                try:
                    chunks = []
                    while True:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        if b'\n' in chunk or sum(len(c) for c in chunks) > 1048576:
                            break
                    raw = b''.join(chunks).decode('utf-8', errors='ignore').strip()
                    msg = None
                    if raw.startswith('{'):
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            msg = None
                    if not isinstance(msg, dict):
                        msg = {'command': raw.lower()}
                    data = str(msg.get('command', '')).strip().lower()
                    if data == 'new':
                        GLib.idle_add(self.add_box)
                    elif data == 'capture':
                        paths = msg.get('paths') or []
                        GLib.idle_add(self.capture_selection, paths)
                    elif data in ('quit', 'exit'):
                        GLib.idle_add(self.quit)
                    # For a plain `desktop-comment-box` while already running,
                    # do not duplicate windows. Just acknowledge it.
                    conn.sendall(b'OK\n')
                except Exception:
                    pass

    def _cleanup_control_socket(self):
        self._server_running = False
        try:
            if self._server_socket:
                self._server_socket.close()
        except Exception:
            pass
        try:
            CONTROL_SOCKET.unlink(missing_ok=True)
        except Exception:
            pass

    def _cleanup_old_drop_launchers(self):
        for base in [DESKTOP_DIR, Path.home() / '.local' / 'share' / 'applications']:
            try:
                for p in base.glob('*desktop-comment-box-drop*.desktop'):
                    p.unlink(missing_ok=True)
            except Exception:
                pass

    def _runtime_repair_config(self):
        # Re-run the same repair while the app is already open.  This catches
        # stale synced-window state from older builds before creating/removing boxes.
        self.config = repair_config(self.config)
        return self.config

    def box_at_root(self, root_x, root_y, margin=0):
        # Return the topmost live comment box under the pointer.  This is used
        # by manual icon dragging so same-box moves, box-to-box moves, and
        # desktop exports are separate decisions.
        wins = list(self.windows.values())
        for win in reversed(wins):
            try:
                if win.get_visible() and win.root_point_inside(root_x, root_y, margin=margin):
                    return win
            except Exception:
                continue
        return None

    def box_for_drag_release(self, root_x, root_y, off_x=0, off_y=0, tile_w=96, tile_h=112):
        """Find the comment box that should receive a dragged icon.

        A simple pointer hit-test was enough for same-box moves, but on some
        Cinnamon/Muffin setups another borderless keep-below window does not
        report the same root origin that GTK gives the source drag widget.  When
        that happens, box-to-box drops get misclassified as Desktop exports.

        First try the pointer point.  If that misses, try overlap between the
        dragged icon tile rectangle and every live box.  This keeps Desktop export
        working while allowing a tile dropped visibly over another box to transfer
        there.
        """
        try:
            target = self.box_at_root(root_x, root_y, margin=22)
            if target is not None:
                return target
        except Exception:
            pass

        try:
            left = int(root_x) - int(off_x)
            top = int(root_y) - int(off_y)
            width = max(64, int(tile_w or 96))
            height = max(72, int(tile_h or 112))
        except Exception:
            return None

        best = None
        best_area = 0
        for win in reversed(list(self.windows.values())):
            try:
                if not win.get_visible():
                    continue
                area = win.root_overlap_area(left, top, width, height, margin=10)
                if area > best_area:
                    best = win
                    best_area = area
            except Exception:
                continue

        # Require a meaningful overlap so dragging near a box does not accidentally
        # import into it.  A 900px² threshold is roughly a 30x30 overlap.
        if best is not None and best_area >= 900:
            return best
        return None

    def _create_window(self, settings):
        # Idempotent: never create two live windows for the same saved box ID.
        # This fixes the case where `desktop-comment-box --new` was launched
        # while no controller was running: add_box() created a window, then run()
        # created the same window again from config.
        box_id = settings.get('id')
        if box_id in self.windows:
            try:
                self.windows[box_id].present()
            except Exception:
                pass
            return self.windows[box_id]
        win = DesktopBoxWindow(self, settings)
        self.windows[settings['id']] = win
        return win

    def capture_selection(self, paths, create_window=True):
        """Create a new box from selected files, preserving desktop positions.

        This is meant to be called by the installed Nemo Action.  It reads
        metadata::nemo-icon-position before the files are moved, computes a
        bounding rectangle, creates a new box around that rectangle, and stores
        the icons at matching local coordinates.
        """
        self._runtime_repair_config()
        log_capture(f'capture called: raw={list(paths or [])!r}')
        selected, rejected = validate_desktop_capture_selection(paths)
        capture_title = 'Selection'
        log_capture(f'capture strict desktop selection valid={[str(p) for p in selected]!r} rejected={rejected!r}')

        # Strict behavior by design: no empty capture, no ~/Desktop itself,
        # no nested Desktop items, and no mixed Desktop/non-Desktop selection.
        if not selected or rejected:
            if not selected:
                msg = f'{APP_ID}: capture ignored: no selected Desktop files were passed. Raw args={list(paths or [])!r}'
                notice = 'Select one or more files directly on the Desktop first.'
            else:
                msg = f'{APP_ID}: capture ignored: selection included non-Desktop or invalid paths: {rejected!r}. Raw args={list(paths or [])!r}'
                notice = 'Only files directly on the Desktop can be captured.'
            print(msg, file=sys.stderr, flush=True)
            log_capture(msg)
            try:
                subprocess.Popen(['notify-send', 'Desktop Comment Box', notice], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            return False

        defaults = self.config.get('defaults', new_default_settings())
        icon = int(defaults.get('icon_size', DEFAULTS['icon_size']))
        tile_w, tile_h = tile_step_for_settings(defaults)

        entries = []
        fallback_x = int(DEFAULTS['x'])
        fallback_y = int(DEFAULTS['y']) + 80
        for idx, p in enumerate(selected):
            pos = get_nemo_icon_position(p)
            source = 'metadata' if pos else 'fallback'
            if not pos:
                pos = (fallback_x + (idx % 5) * tile_w, fallback_y + (idx // 5) * tile_h)
            entries.append({'path': p, 'abs_x': int(pos[0]), 'abs_y': int(pos[1]), 'source': source})

        min_x = min(e['abs_x'] for e in entries)
        min_y = min(e['abs_y'] for e in entries)
        max_x = max(e['abs_x'] for e in entries) + tile_w
        max_y = max(e['abs_y'] for e in entries) + tile_h

        # Place the box around the selected desktop-icon grid.  Nemo icon
        # metadata is stored in desktop coordinates, so keep the selected bounds
        # intact and translate each icon into the box's local grid.
        box_x = max(0, min_x - CAPTURE_BOX_PADDING - GRID_MARGIN_X)
        box_y = max(0, min_y - TITLEBAR_CAPTURE_OFFSET - GRID_MARGIN_Y)
        width = max(MIN_BOX_WIDTH, (max_x - min_x) + (CAPTURE_BOX_PADDING * 2) + (GRID_MARGIN_X * 2))
        height = max(MIN_BOX_HEIGHT, (max_y - min_y) + TITLEBAR_CAPTURE_OFFSET + (CAPTURE_BOX_PADDING * 2) + GRID_MARGIN_Y)
        width, height = clamp_size(width, height)
        log_capture('capture positions: ' + repr([(e['path'].name, e['abs_x'], e['abs_y'], e['source']) for e in entries]))
        log_capture(f'capture bounds: min=({min_x},{min_y}) max=({max_x},{max_y}) box=({box_x},{box_y},{width},{height})')

        settings = make_box_from_defaults(defaults, title=capture_title, offset=0)
        settings['x'] = int(box_x)
        settings['y'] = int(box_y)
        settings['width'] = int(width)
        settings['height'] = int(height)
        settings['positions'] = {}
        folder = Path(settings['folder']).expanduser()
        folder.mkdir(parents=True, exist_ok=True)

        for e in entries:
            src = e['path']
            old_name = src.name
            try:
                dest = move_path_to(src, folder)
            except Exception as ex:
                print(f'{APP_ID}: capture move failed for {src}: {ex}', file=sys.stderr, flush=True)
                continue
            local_x = int(e['abs_x'] - box_x - CAPTURE_BOX_PADDING)
            local_y = int(e['abs_y'] - box_y - TITLEBAR_CAPTURE_OFFSET)
            gx, gy = xy_to_grid_cell(settings, local_x, local_y)
            local_x, local_y = grid_cell_to_xy(settings, gx, gy)
            settings['positions'][dest.name] = {'x': local_x, 'y': local_y}
            settings['positions'].pop(old_name, None)

        self.config.setdefault('boxes', []).append(settings)
        self.save()
        log_capture(f'created selection box id={settings.get('id')} moved={len(settings.get('positions', {}))} folder={settings.get('folder')}')
        if create_window:
            self._create_window(settings)
        return False

    def add_box(self, save=True, create_window=True):
        self._runtime_repair_config()
        offset = 40 * len(self.config.get('boxes', []))
        settings = make_box_from_defaults(self.config.get('defaults', new_default_settings()), title=None, offset=offset)
        # Guarantee that the new box is unique against any repaired/stale config.
        existing_ids = {str(b.get('id')) for b in self.config.get('boxes', []) if isinstance(b, dict)}
        while settings.get('id') in existing_ids:
            settings['id'] = str(uuid.uuid4())
            settings['folder'] = str(BOX_DIR / settings['id'])
        folder = Path(settings['folder']).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        self.config.setdefault('boxes', []).append(settings)
        if create_window:
            self._create_window(settings)
        if save:
            self.save()

    def remove_box(self, box_id):
        self._runtime_repair_config()
        win = self.windows.pop(box_id, None)
        settings = None
        for box in self.config.get('boxes', []):
            if box.get('id') == box_id:
                settings = box
                break
        if settings:
            folder = Path(settings.get('folder', ''))
            try:
                if folder.exists() and folder.is_dir():
                    for item in list(folder.iterdir()):
                        move_path_to(item, DESKTOP_DIR)
                    folder.rmdir()
            except Exception as e:
                print(f'{APP_ID}: remove box cleanup failed: {e}', file=sys.stderr, flush=True)
            self.config['boxes'] = [b for b in self.config.get('boxes', []) if b.get('id') != box_id]
            self.save()
        if win:
            win.destroy_window_only()
        if not self.config.get('boxes'):
            self.save()
            Gtk.main_quit()

    def copy_defaults_from_box(self, settings):
        defaults = self.config.setdefault('defaults', new_default_settings())
        for key in STYLE_KEYS:
            if key in settings:
                defaults[key] = settings[key]
        # New boxes should use the current box dimensions too.
        for key in ['width', 'height']:
            if key in settings:
                defaults[key] = settings[key]
        self.save()

    def save(self):
        save_config(self.config)

    def quit(self):
        self.save()
        self._cleanup_control_socket()
        Gtk.main_quit()


if __name__ == '__main__':
    ensure_dirs()
    create_new = '--new' in sys.argv
    repair_only = '--repair' in sys.argv
    capture_selected = '--capture-selected' in sys.argv
    capture_paths = []
    if capture_selected:
        idx = sys.argv.index('--capture-selected')
        capture_paths = [arg for arg in sys.argv[idx + 1:] if not arg.startswith('--')]

    if repair_only:
        cfg = load_config(create_initial=False)
        save_config(cfg)
        print('Desktop Comment Box config repaired.')
        sys.exit(0)

    # If another controller process is already running, send the command there
    # and exit. This prevents synced duplicate windows.
    if capture_selected:
        if send_capture_to_running(capture_paths):
            sys.exit(0)
    elif send_command_to_running('new' if create_new else 'show'):
        sys.exit(0)

    app = DesktopCommentBoxApp(create_initial=(not create_new and not capture_selected))
    if create_new:
        # When no controller is already running, create the saved box entry but
        # let run() create its window exactly once.
        app.add_box(save=True, create_window=False)
    if capture_selected:
        app.capture_selection(capture_paths, create_window=False)
    app.run()
