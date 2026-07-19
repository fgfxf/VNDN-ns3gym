#!/usr/bin/env python
# -*- coding: utf-8 -*-

# python 3.6 3.7 3.8
# check pygraphviz pycairo PyGObject pygccxml for python3.8
# pip install pygraphviz pycairo PyGObject pygccxml
# ./waf xxxx --vis
# This script checks whether vis is useful


mods = [
    "gi",
    "cairo",
    "pygraphviz",
]

for module_name in mods:
    try:
        __import__(module_name)
        print("[OK]", module_name)
    except Exception as e:
        print("[FAIL]", module_name, repr(e))

try:
    import gi

    versions = {
        "GObject": "2.0",
        "Gtk": "3.0",
        "Gdk": "3.0",
        "Pango": "1.0",
        "GooCanvas": "2.0",
    }

    for name, version in versions.items():
        try:
            gi.require_version(name, version)
            module = __import__("gi.repository", fromlist=[name])
            getattr(module, name)
            print("[OK] gi.repository." + name)
        except Exception as e:
            print("[FAIL] gi.repository." + name, repr(e))

except Exception as e:
    print("[FAIL] import gi:", repr(e))
