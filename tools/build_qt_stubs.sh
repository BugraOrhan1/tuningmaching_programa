#!/usr/bin/env bash
# Herbouwt de libGL/libEGL/libxkbcommon/libXrender/libdbus-stubs die PySide6
# offscreen nodig heeft op systemen zonder deze bibliotheken (bv. de Arena-sandbox).
#
# Gebruik:
#   bash tools/build_qt_stubs.sh /home/user/qtlibs [pad-naar-PySide6-Qt-lib]
# Daarna testen met:
#   LD_LIBRARY_PATH=<stubs> QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
set -euo pipefail

OUT="${1:-/home/user/qtlibs}"
QT_LIB="${2:-.venv/lib/python3.11/site-packages/PySide6/Qt/lib}"
QT_PLUGINS=".venv/lib/python3.11/site-packages/PySide6/Qt/plugins"
mkdir -p "$OUT"

# Alle undefined symbolen uit de Qt-libs én de platform-plugins verzamelen.
UNDEF="$(mktemp)"
for lib in "$QT_LIB"/libQt6*.so*; do
  nm -D --undefined-only "$lib" 2>/dev/null | awk '$1=="U"{print $2}' || true
done | sed 's/@.*//' | sort -u > "$UNDEF"
find "$QT_PLUGINS" -name "*.so*" -exec nm -D --undefined-only {} \; 2>/dev/null \
  | awk '$1=="U"{print $2}' | sed 's/@.*//' | sort -u > "$UNDEF.plugins" || true

stub() { # stub <soname> <symbol-regex> <bronbestand-met-undefs...>
  local name="$1" pattern="$2" src syms
  shift 2
  syms=$( { grep -hE "$pattern" "$@" 2>/dev/null || true; } | sort -u )
  { echo "void __stub(void){}"; for s in $syms; do echo "void $s(void){__stub();}"; done; } \
    > "$OUT/${name}.c"
  gcc -shared -fPIC -Wl,-soname,"$name" -o "$OUT/$name" "$OUT/${name}.c"
  echo "$name: $(echo -n "$syms" | grep -c .) symbolen"
}

stub libGL.so.1       '^gl[A-Z]'   "$UNDEF" "$UNDEF.plugins"
stub libEGL.so.1      '^egl[A-Z]'  "$UNDEF"
stub libXrender.so.1  '^XRender'   "$UNDEF"

# libxkbcommon vereist version-node V_0.5.0.
printf 'V_0.5.0 {\n  global:\n    xkb_*;\n};\n' > "$OUT/xkb_version.map"
syms=$(grep -E '^xkb_' "$UNDEF" | sort -u)
{ echo "void __stub(void){}"; for s in $syms; do echo "void $s(void){__stub();}"; done; } > "$OUT/libxkbcommon.so.0.c"
gcc -shared -fPIC -Wl,-soname,libxkbcommon.so.0 -o "$OUT/libxkbcommon.so.0" \
  "$OUT/libxkbcommon.so.0.c" -Wl,--version-script="$OUT/xkb_version.map"
echo "libxkbcommon.so.0: $(echo -n "$syms" | grep -c .) symbolen (V_0.5.0)"

# libdbus vereist version-node LIBDBUS_1_3.
printf 'LIBDBUS_1_3 {\n  global:\n    dbus_*;\n  local: *;\n};\n' > "$OUT/dbus_version.map"
syms=$( { nm -D --undefined-only "$QT_LIB/libQt6DBus.so.6" 2>/dev/null | awk '$1=="U"{print $2}' || true; } \
  | sed 's/@.*//' | grep -E '^(dbus_)' | sort -u)
{ echo "void __stub(void){}"; for s in $syms; do echo "void $s(void){__stub();}"; done; } > "$OUT/libdbus-1.so.3.c"
gcc -shared -fPIC -Wl,-soname,libdbus-1.so.3 -o "$OUT/libdbus-1.so.3" \
  "$OUT/libdbus-1.so.3.c" -Wl,--version-script="$OUT/dbus_version.map"
echo "libdbus-1.so.3: $(echo -n "$syms" | grep -c .) symbolen (LIBDBUS_1_3)"

rm -f "$UNDEF" "$UNDEF.plugins"
echo "Klaar. Testen met: LD_LIBRARY_PATH=$OUT QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q"
