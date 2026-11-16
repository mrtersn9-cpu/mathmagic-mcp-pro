# Sorun giderme

| Belirti | Neden / çözüm |
| --- | --- |
| Claude Desktop aracı görmüyor | Uygulamayı tamamen kapatıp açın. `%APPDATA%\Claude\claude_desktop_config.json` içinde `mcpServers.mathmagic-mcp-pro` girdisini kontrol edin. |
| `pywin32_installed=false` | `.venv\Scripts\python.exe -m pip install -r requirements-windows.txt` |
| `mathmagic_executable_exists=false` | Gerçek `.exe` yolunu `MATHMAGIC_EXE` içinde düzeltin; `InD.exe` sürümü gerekli. |
| `indesign_plugin_folder_exists=false` | `MathMagic CC2026-64bit` klasörünü doğru InDesign 2026 `Plug-Ins` içine kopyalayıp InDesign'ı yeniden açın. |
| `InDesign COM timeout` | Açık modal pencere, lisans uyarısı veya COM kaydı. InDesign'da manuel işlem deneyin; kalırsa InDesign'ı düzgün yeniden başlatın. |
| `New Equation` action not found | `mathmagic_inspect_indesign` çıktısındaki gerçek menü adını `MATHMAGIC_NEW_ACTION` değişkenine yazın; menüde eklenti etkin mi bakın. |
| `Menu action disabled` | Metin imleci veya uygun MathMagic nesnesi seçili değil; InDesign MCP seçimini kontrol edin. |
| MathMagic penceresi bulunamadı | `MATHMAGIC_EXE` yolu, lisans iletişim kutusu ve editör açılmasını kontrol edin. Uygulamayı yönetici olarak, Claude'u normal kullanıcı olarak çalıştırmak erişim engelleyebilir. |
| `Multiple MathMagic windows` | Diğer MathMagic belgelerini kapatın; tek editör penceresiyle tekrar deneyin. |
| Yapıştırılan TeX düz metin kaldı | MathMagic sürümünde `Shift+Enter` dönüşümünün çalıştığını elle test edin. TeX söz dizimini sadeleştirin. |
| Formül yanlış yere kondu | Eklenti çağrısı öncesi InDesign seçim/imleç değişmiş olabilir. İşlem sırasında diğer MCP'yi kullanmayın. |
| Formül yanlış dönüştü | Otomatik doğrulama yok. Kaynak TeX'i inceleyin; gerekirse MathMagic editöründe elle düzeltin. |
| `SUBMITTED_UNVERIFIED` | **Normal beklenen durumdur**. Komutlar gönderildi; düzenlenebilirliği ve görünümü kontrol etmeniz gerekir. |
| Pano içeriği değişti | Yalnız metin panosu saklanıp geri konabilir; görüntü/zengin biçim geri yüklenmez. İşlem öncesi önemli panoyu koruyun. |
| `FAILED_OR_PARTIAL` | Kısmi değişiklik olabilir. Aynı komutu düşünmeden tekrar etmeyin; test belgesini kontrol edin. |

## Tanı komutları

```powershell
cd C:\Tools\mathmagic-mcp-pro
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -u .\server.py
```

İkinci komut sessizce stdin beklentisinde kalmalıdır (`Ctrl+C` ile çıkın). Başlangıçta hata basıyorsa Claude bağlanamaz.

Claude Desktop MCP logları: `%APPDATA%\Claude\logs\`.