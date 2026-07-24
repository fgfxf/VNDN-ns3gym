# castxml binary
ubuntu 18.04 系统仓库castxml版本过低(v0.1)，ns3要求至少v0.2
因此我们采用python3.7仓库中的castxml二进制发布版本。

```bash
git lfs pull
git lfs ls-files
cp -r castxml  ~/.local/lib/python3.8/site-packages/
cp -r castxml-0.4.5.dist-info ~/.local/lib/python3.8/site-packages/
```

```bash
castxml --version

python3.8 ~/.local/bin/castxml --version

castxml version 0.4.5

CastXML project maintained and supported by Kitware (kitware.com).

clang version 13.0.0 (https://github.com/CastXML/CastXMLSuperbuild 3a0a2c545e708f63908639f7ea8799b5f03b8fc0)
Target: x86_64-unknown-linux-gnu
Thread model: posix
InstalledDir:
```
