# check_pyvis

ns3/ndnsim 有节点可视化功能，官方安装命令为
```bash
# ubuntu 18.04
pip install pygraphviz pycairo PyGObject pygccxml
```
系统内置python为python3.6，但是我们需要python3.8

因此我们需要分别为python3.8 安装上述四个pip库。
```bash
sudo apt install -y \
    python3.8-dev \
    python3.8-venv \
    build-essential \
    pkg-config \
    libcairo2-dev \
    libgirepository1.0-dev \
    gobject-introspection \
    libffi-dev \
    graphviz \
    libgraphviz-dev \
    gir1.2-gtk-3.0 \
    gir1.2-pango-1.0 \
    gir1.2-goocanvas-2.0 \
    libgoocanvas-2.0-dev

# 将/usr/bin/python3和/usr/bin/python软链接到/usr/bin/python3.8

python -m pip install --no-cache-dir "pycairo==1.23.0"
python -m pip install --no-cache-dir "PyGObject==3.42.2"
python -m pip install --no-cache-dir "pygraphviz==1.7"

```

使用这个脚本检测是否安装成功。
```bash
[OK] gi
[OK] cairo
[OK] pygraphviz
[OK] gi.repository.GObject
[OK] gi.repository.Gtk
[OK] gi.repository.Gdk
[OK] gi.repository.Pango
[OK] gi.repository.GooCanvas
```


