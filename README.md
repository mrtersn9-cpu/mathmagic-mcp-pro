# MathMagic MCP Pro (Windows / InDesign 2026)

[![Status](https://img.shields.io/badge/status-experimental-orange)](#what-works-and-what-is-unverified)

**Claude Desktop + Adobe InDesign 2026 + MathMagic Pro 9.31** için yerel MCP sunucusu.
Mevcut InDesign MCP'nizi **değiştirmez**; yanında ayrı bir araç seti olarak çalışır.

## v0.3 — Pro mesaj adaptörü (önerilen giriş noktası: `server_pro.py`)

v0.3, v0.1'in klavye/pano adaptörünün yerine **Windows pencere mesajları** kullanır (`WM_CHAR`, `WM_COMMAND`, `WM_SETTEXT`). Fare, klavye, pano, `SetFocus`/`SetForegroundWindow` kullanmaz. Lisans penceresine dokunmaz.

Gerçek bir Windows 11 + InDesign 2026 + MathMagic Pro 9.31 (deneme modu) ortamında canlı test edildi:

- **`offline` (varsayılan):** MathMagic EPS üretir, InDesign işaretçiye `place()` ile yerleştirir, belgeye gömer ve eklentinin *Default Baseline* ayarını uygular. Ölçülen hız ~1,2–1,8 sn/formül. Testlerde kullanıcının öndeki uygulamasını öne çekmedi.
- **`plugin`:** Eklentinin New/Edit Equation eylemi → bağlı MathMagic penceresi (mesajla) → *Update* (32880). Ölçülen hız ~2–3,5 sn/formül. Eklentinin kendisi her formülde pencereleri öne getirir.
- **Araçlar:** 19 araç; değişiklik yapanların hepsi `confirm=true` ister. Toplu iş zaman bütçeli çalışır ve `next_index` ile kaldığı yerden devam eder (2000 formüle kadar). Her sonuçta doğrulama ve ön plan (odak) raporu döner.
- **Bilinen sınırlar:**
  - Deneme modunda her açılışta lisans penceresi çıkar ve bazı EPS çıktılarında "Demo" filigranı olur.
  - Stil setindeki eksik yazı tipi uyarısı otomatik onaylanır, ama stil setinin düzeltilmesi gerekir.

Ayrıntılar: [`docs/PRO_V03_TR.md`](docs/PRO_V03_TR.md). Claude kaydı: `command` = `.venv\Scripts\python.exe`, `args` = `["-u", "<proje>\\server_pro.py"]`, `env.MATHMAGIC_DEFAULT_MODE` = `offline`.

> **Önemli (v0.1/v0.2 için geçerli not):** Bu bir *doğrulanmış MathMagic API entegrasyonu* değildir. MathMagic'in belgelenmiş bir Windows otomasyon API'si bulunamadı. InDesign menü eylemi Windows COM/ExtendScript ile çağrılır; dış MathMagic editörü daha hızlı, hedefli bir `pywinauto`/klavye adaptörüyle kontrol edilmeye *çalışılır*. Gerçek InDesign 2026 + MathMagic 9.31 ortamında henüz uçtan uca test edilmemiştir. Formülün başarıyla işlendiği **otomatik olarak varsayılmaz**.

## Mimari

```text
Claude Desktop
  ├── mevcut InDesign MCP → sayfa, metin, soru konumu, [[MM:ID]] işaretleri
  └── mathmagic-mcp-pro (stdio / yerel Python)
        ├── Preflight, LaTeX doğrulama, iş kaydı
        ├── InDesign COM → DoScript(ExtendScript)
        │      └── Plug-Ins > MathMagic > New/Edit Equation menü eylemi
        └── MathMagic 9.31 InD.exe (hedefli pencere otomasyonu)
               ├── LaTeX yapıştırma
               ├── Shift+Enter (TeX → equation)
               └── Ctrl+S (kaydet ve InDesign'a geri dön)
```

**Genel Windows MCP veya ekran görüntüsü/OCR kullanmaz.** Yine de MathMagic'in dış editöründe kullanıcı arayüzü otomasyonuna bağımlıdır; pencerelerin açılması, odak ve lisans diyalogları hâlâ sorun çıkarabilir.

## Hızlı kurulum

Gerekenler: **Windows 10/11**, **Python 3.10+**, **Claude Desktop**, **Adobe InDesign 2026**, **MathMagic Pro 9.31 InD.exe**, InDesign `Plug-Ins\MathMagic CC2026-64bit` eklentisi. InDesign menüsünden **MathMagic → New Equation** işleminin elle çalıştığını doğrulayın.

1. Bu projeyi bilgisayarınıza indirin veya ZIP'i açın (ör. `C:\Tools\mathmagic-mcp-pro`).
2. Proje klasöründe PowerShell açın ve çalıştırın:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```
3. Betik, mevcut Claude Desktop MCP yapılandırmasını **yedekler** ve `mathmagic-mcp-pro` girdisini ekler. Mevcut InDesign MCP korunur.
4. Claude Desktop'ı tamamen kapatıp yeniden açın.
5. Claude'a sırasıyla **`mathmagic_preflight`**, **`mathmagic_inspect_indesign`**, **`mathmagic_preview_equation`** çağrılarını yaptırın.
6. Önce *orijinal olmayan* bir InDesign test belgesinde tek formül deneyin.

Detaylı Türkçe rehber: [`docs/KURULUM_TR.md`](docs/KURULUM_TR.md)

## Kullanılabilir araçlar

| MCP aracı | Görev | Belge değiştirir mi? |
| --- | --- | --- |
| `mathmagic_preflight` | Sürüm/yol/bağımlılık kontrolü | Hayır |
| `mathmagic_inspect_indesign` | Belge ve MathMagic menü eylemlerini bul | Hayır |
| `mathmagic_preview_equation` | Tek formülü doğrula; işlem planını göster | Hayır |
| `mathmagic_create_equation` | Seçili metin noktasına MathMagic formülü eklemeyi dene | **Evet**, `confirm=true` |
| `mathmagic_edit_equation` | Seçili MathMagic nesnesini yeniden düzenlemeyi dene | **Evet**, `confirm=true` |
| `mathmagic_backup_indd` | Son kaydedilmiş INDD dosyasını başka klasöre kopyala | Kaynak hayır |
| `mathmagic_check_marker` | Tekil `[[MM:ID]]` işaretçisini incele | Hayır |
| `mathmagic_preview_batch` | 1–100 formüllük JSON iş listesini kontrol et | Hayır |
| `mathmagic_run_batch_first` | Listede `start_index` konumundaki **tek** formülü uygula ve dur | **Evet**, `confirm=true` |
| `mathmagic_cleanup_marker` | Kontrol sonrası işaretçiyi kaldır | **Evet**, çift onay |

> Toplu süreç bilinçli olarak her formülde durur. **100 formülü gözetimsiz ve garantili biçimde dönüştürüyor** iddiası yoktur. `start_index` ile sonraki işe geçilebilir.

## Çalışma örneği

Mevcut InDesign MCP ile `[[MM:Q001]]` işaretini ilgili soru metnine koyun; ardından Claude'a:

> MathMagic MCP araçlarını kullan. `mathmagic_inspect_indesign` ile eylemleri doğrula. `[[MM:Q001]]` konumuna `\frac{3}{4}+\frac{1}{2}` formülünü MathMagic üzerinden eklemeyi önce önizle, sonra onay verdiğimde uygula. MathMagic'te kaydedildiğini ve InDesign'da düzenlenebilir olduğunu **görsel inceleme yapılmadan kesin doğrulanmış sayma**.

Örnek manifest: [`examples/equations.json`](examples/equations.json)

## What works and what is unverified

- ✅ MCP stdio protokolü, araç listesi, giriş doğrulama, kuru çalışma, iş kayıtları ve testleri yerel ortamda çalıştırıldı.
- ✅ Kaynak kodda InDesign COM/DoScript köprüsü ve MathMagic süreç yolunu denetleyen pencere adaptörü bulunuyor.
- ⚠️ Windows üzerinde gerçek COM/plug-in çağrıları ve LaTeX dönüştürme akışı bu geliştirme ortamında test edilemedi.
- ⚠️ MathMagic editörünün `Ctrl+A`, `Ctrl+V`, `Shift+Enter`, `Ctrl+S` tepkileri kurulu sürümde ayrıca doğrulanmalı.
- ❌ Matematiksel eşdeğerlik, yüzde yüz doğru tipografi, formülün *native MathMagic object* olması veya çift tıklayarak açılabilirliğinin otomatik doğrulanması **henüz uygulanmadı**.
- ❌ Yerel vendor C++ `.InDesignPlugin` eklentisi üretilmedi. Program, **mevcut resmî MathMagic eklentisini çağırır**.

## Güvenlik

- Yerel stdio dışında ağ dinleyicisi yoktur; API anahtarı gerekmez.
- Dosya mutasyonları açık `confirm=true` gerektirir.
- Asıl `.indd` belgeyi otomatik kaydetmez, üzerine yazmaz, silmez.
- Denetim kayıtlarına ham formül yazılmaz; SHA-256 özeti yazılır.
- Tek süreç içinde eşzamanlı MathMagic işleri kilitlenir. **Diğer InDesign MCP de aynı anda belge düzenlememelidir.** İki bağımsız MCP arasında küresel kilit bulunmuyor.
- Pano metin yedeği alınabilirse geri yüklenir; görüntü gibi metin dışı pano verisinin korunması garanti edilmez.

## Belgeler

- [Kurulum ve test (TR)](docs/KURULUM_TR.md)
- [Mimari, veri akışı ve sınırlamalar](docs/MIMARI.md)
- [Araç API sözleşmesi](docs/API.md)
- [Matbaa / soru bankası kalite kontrol](docs/KALITE_KONTROL.md)
- [Sorun giderme](docs/SORUN_GIDERME.md)
- [Güvenlik ve ürünleştirme yol haritası](docs/GUVENLIK_YOL_HARITASI.md)

## Kaynaklar

- MathMagic Pro/InDesign kurulum ve `New Equation` açıklaması: https://mathmagic.com.hk/pro.html
- MathMagic LaTeX yapıştırma ve **Shift+Return**: https://mathmagicturkiye.com/support/faqs.html
- InDesign Windows COM `DoScript` uygulama örneği: https://github.com/Tlechanteur/indesign-mcp-server-windows/blob/main/WINDOWS.md
- Adobe InDesign betik otomasyonu: https://helpx.adobe.com/indesign/desktop/automation-and-scripting/document-automation/automate-workflows-with-scripts.html
- MCP stdio ve Claude Desktop: https://modelcontextprotocol.io/docs/develop/build-server

## Lisans

Kaynak kodu `LICENSE` altındaki MIT lisansı ile sağlanmıştır. MathMagic ve Adobe InDesign ticari ürünleridir ve bu depoya dahil değildir.