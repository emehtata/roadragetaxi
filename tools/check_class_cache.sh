#!/bin/sh
# Every class_name in godot/*.gd must be in the Godot class cache (stale cache = parse errors).
cache=godot/.godot/global_script_class_cache.cfg
[ -f "$cache" ] || { echo "missing $cache; run make godot/.godot/import-stamp" >&2; exit 1; }
status=0
for name in $(grep -rh '^class_name' godot --include=*.gd --exclude-dir=.godot | awk '{print $2}'); do
	grep -q "&\"$name\"" "$cache" || { echo "class cache lacks $name" >&2; status=1; }
done
exit $status
