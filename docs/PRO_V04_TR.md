# MathMagic MCP Pro v0.4.2 — Kullanım Kılavuzu

**Giriş noktası:** `server_pro.py` (Claude kaydı `mathmagic-mcp-pro`, ortam değişkeni `MATHMAGIC_DEFAULT_MODE=offline`).

**Komut envanteri:** [`MATHMAGIC_KOMUT_ENVANTERI_TR.md`](MATHMAGIC_KOMUT_ENVANTERI_TR.md). MathMagic'in 213 menü komutunun ve 13 eklenti eyleminin canlı sınıflandırması bu belgede.

## v0.4.2 değişiklikleri (17.11.2026): geometri şapkası ve yay

- **Yeni yazımlar:**
  - `\widehat{..}` geniş üçgen şapka verir (MathMagic Wide Hat, `V(42)`).
  - `\overarc{..}`, `\wideparen{..}` ve `\overparen{..}` yay verir (Over Elliptical Arc, `V(19)`).
- **Neden?** MathMagic'in TeX dönüştürücüsü bu komutları kuramıyor:
  - `\widehat` içeriği siliyor;
  - `\wideparen` düz metin oluyor;
  - `\overparen` hata veriyor.
- **Nasıl?** Formül `\overbrace` yer tutucusuyla yazılır ve yapı doğrulanır. MathMagic `.mmf` biçiminde kaydedilir, yer tutucu simge `V(15)` hedef simgeyle değiştirilir. Dosya File > Open ile (yeni `open_file`, yalnız mesajlarla) açılır ve EPS'e aktarılır. Geçici `.mmf` dosyaları `%TEMP%\MathMagicMCP\native` altında oluşur ve başarıdan sonra silinir.
- **Karşılaştırıcı:** Çok basamaklı sayılar tek birim sayılır (`60^{\circ}` = `{60}^{\circ}`); `\widehat` ve `\overbrace` tanınır.
- **Canlı testte bulunan iki hata düzeltildi:**
  - Aynı formülü yeniden üretirken açık `.mmf` dosyasının üzerine kaydetmek "replace?" penceresi açıyordu. Artık geçici dosya adları benzersiz.
  - Doğrulama kapalıyken çalışma belgesine bağlı dosya ikinci kez açılamıyordu ("File already opened"). Artık değiştirilmiş içerik ayrı bir dosyaya yazılıyor.
- **Ölçüm:** Şapka yüksekliği 12 pt'de 2,85 pt, 24 pt'de 2,22 pt ekliyor. Yükseklik StyleSet'teki "Embellishment height" değerine bağlı.

## v0.4.1 değişiklikleri (17.11.2026, soru bankası canlı E2E testinden)

- **Kullanıcı girdisi koruması:**
  - Sorun: Kullanıcı Alt+Tab için Alt tuşunu basılı tutarken MathMagic'e gönderilen karakterler kayboldu ve formül boş çıktı. Hata canlıda üç kez görüldü; LaTeX doğrulaması üçünü de yakaladı.
  - Çözüm: Araç yazmadan önce Alt/Ctrl/Shift/Win tuşlarının bırakılmasını bekler. Bu yalnız okuma yapan `GetAsyncKeyState` çağrısıdır; tuş gönderilmez.
  - Boş formül bir kez yeniden denenir; ikinci denemede de boşsa sonuç `EMPTY_RENDER` olur. Canlı testte araç 2,5 sn bekledi ve formül eksiksiz çıktı.
- **Odak raporu:** `took_focus_from_user` artık yalnız MathMagic veya InDesign öne geldiğinde `true` olur. Kullanıcının kendi uygulama geçişleri `user_switched_apps` alanında ayrıca raporlanır. Eski sürüm bunları da odak kaybı sayıyordu.
- **LaTeX karşılaştırma:** `\dfrac`, `\tfrac`, `\cfrac` = `\frac`; `\dbinom`, `\tbinom` = `\binom` sayılır. MathMagic `\dfrac{12}{18}` ifadesini `\mbox{\Large $\frac{12}{18}$}` olarak dışa aktarıyordu ve eski sürüm bunu yanlışlıkla `LATEX_MISMATCH` sayıyordu.
- **Toplu iş sonuçları:** Her satır artık uyuşmazlıkta `latex_exported` (MathMagic'in kurduğu LaTeX), ayrıca varsa `empty_render_retries`, `user_modifier_keys_waited`, `latex_rewrites` ve `user_switched_apps` alanlarını içerir.
- **Stil durumu:** `apply_styleset` sonrasında durum dosyasındaki punto ve yazı tipi bilgisi artık uygulanan StyleSet'ten alınıyor; eski değer kalmıyor.
- **Sunucu talimatları:** İstemciye MCP `instructions` alanı gönderiliyor. İçeriği: tek kanal (Windows MCP yasak), lisans penceresi kuralı, iş akışı, hata kodları ve dizgi notu.
- **Dizgi bulgusu:** Üst üste kesirli satır içi formüllerde Otomatik satır aralığı çakışma yaratıyor. 12 pt metinde 21 pt sabit satır aralığı (yaklaşık 1,75 kat) sorunu çözdü.
- **Yazı tipi bulgusu:** StyleSet'te Myriad Pro, MathMagic yazı tipi uyarısı verdi (EPS'e gömülse de). Times New Roman uyarısız çalıştı.
- **Soru bankası entegrasyonu:** soru-bankasi-uret-pro skill'i (`scripts/prepare_mathmagic.py`, `indesign/MATHMAGIC-ENTEGRASYON.md`) işaretçili iş emirlerini ve manifestleri üretir.

## Temel ilkeler

- **Kullanılmayanlar:** Klavye, fare, pano ve `SetFocus`/`SetForegroundWindow`.
- **Kullanılanlar:** Yalnızca pencere mesajları ve InDesign COM'da sabit JSX.
- **Sınırlar:** Lisans penceresine dokunulmaz. Belge, yalnızca istenirse kaydedilir (`save_every` veya `mathmagic_save_document`).
- **Onay:** Değişiklik yapan her araç `confirm=true` ister.
- **Kilit:** Değişiklik yapan araçlar süreçler arası kilit altında çalışır. Başka bir Claude oturumu çalışıyorsa araç `BUSY` döndürür.

## Senkronizasyon yapısı

| Konu | Çözüm |
|---|---|
| Sabit beklemeler yerine sıralı bariyer | Yazma, seçme ve dönüştürme kuyruğa tek seferde gönderilir. Ardından gelen Save As penceresi ya da Update ile pencerenin kapanması, öncekilerin işlendiğini kanıtlar. |
| Modal pencereler | Sıkı koruma uygulanır. Beklenmeyen pencerede araç durur ve hiçbir komut göndermez; kural ihlali MathMagic'i çökertebiliyor (`0xc000041d`). Hata kutuları okunur, kapatılır ve `MATHMAGIC_ERROR` olarak raporlanır. |
| Birden çok MathMagic süreci | Koruma, işlem yapılan süreçle sınırlıdır. Eklentinin açtığı ayrı süreçteki lisans penceresi çevrimdışı işi durdurmaz. |
| Sürecin kapanması | MathMagic InD son belge kapanınca çıkar. Bu yüzden bir çalışma belgesi hep açık tutulur ve 25 kullanımda bir tazelenir (`MATHMAGIC_RECYCLE_EVERY`). |
| InDesign tarafı | Her formül tek bir "Geri Al" adımıdır. Çerçeve etiketleri (`mm.id`, `mm.latex`, `mm.sha`, `mm.style`, `mm.tool`) kalıcı kimlik sağlar. |
| Toplu iş | `<manifest>.progress.jsonl` iş günlüğü tutulur. Aynı LaTeX'le daha önce eklenmiş formüller atlanır (`SKIPPED_ALREADY_DONE`). MathMagic kapanırsa bir kez yeniden başlatılır. `next_index` ile kalınan yerden devam edilir. |
| İçerik kalitesi | **LaTeX geri doğrulaması varsayılan olarak açıktır.** MathMagic'in dışa aktardığı LaTeX, yazılanla yapısal olarak karşılaştırılır. |
| Bilinen MathMagic hatası | `\int_0^1 x^2 dx` ve `\sum_k k^2` gibi yazımlarda üs, operatörün tamamına bağlanıyor (canlı doğrulandı). Araç bu terimleri otomatik olarak `{x^2}` biçiminde paketler ve değişikliği `latex_rewrites` alanında raporlar. |

## Araçlar (27)

**Salt okunur**
- `policy`, `preflight`, `status`, `capabilities`, `inspect_indesign`, `probe_uia`
- `preview_equation`, `preview_batch`
- `verify_equation`, `list_equations`, `get_style`, `capture_editor`

**Değişiklik yapanlar**
- `launch`, `dismiss_dialogs`
- `create_equation`, `edit_equation`
- `export_equation` (EPS, SVG, MathML, PNG, LaTeX, AsciiMath…), `render_eps`, `place_eps`
- `run_batch`, `rerender_equations`
- `set_style`, `apply_styleset`
- `prepare_offline_batch`, `backup_indd`, `save_document`, `cleanup_marker`

(Tüm adların başında `mathmagic_` öneki vardır.)

## Yazı tipi ve punto

1. Mevcut ayarı görmek için `mathmagic_get_style` kullanın. Şu anki varsayılan: Helvetica Neue, 12 pt, dik değişkenler.
2. Yeni stil için örnek çağrı: `mathmagic_set_style(name="Kitap 9pt", font="Times New Roman", size_pt=9, variable_italic=true, confirm=true)`.
   - Araç önce mevcut varsayılanı `MCP-yedek-…` adıyla saklar, ardından yeni stili varsayılan yapar.
   - Bir deneme formülü üretip yazı tiplerini ve yüksekliği raporlar.
   - Canlı testte EPS yazı tipleri TimesNewRomanPS oldu ve yazı tipi uyarısı kalktı.
3. Daha önce eklenmiş, etiketli formülleri yeni stile çevirmek için `mathmagic_rerender_equations(confirm=true)` kullanın. Ölçek %100'e sabitlenir, taban çizgisi yeniden uygulanır.
4. Eski stile dönmek için `mathmagic_apply_styleset(name="MCP-yedek-…", confirm=true)` kullanın.
5. Tek bir formülün puntosunu değiştirmek için `size_pt` parametresi var. Ancak kitap genelindeki punto için stil seti kullanın.

## Soru bankası iş akışı (önerilen)

1. Yazı tipini ve puntoyu bir kez `mathmagic_set_style` ile ayarlayın.
2. InDesign MCP ile formül yerlerine `[[MM:Q0001]]` gibi işaretçiler koyun. Manifest dosyası şu biçimde olmalı: `{"equations":[{"id":"Q0001","marker":"[[MM:Q0001]]","latex":"..."}]}`.
3. Sırasıyla `mathmagic_backup_indd` ve `mathmagic_preview_batch` çalıştırın.
4. `mathmagic_run_batch(confirm=true, time_budget_s=600, save_every=50)` çalıştırın. Çağrı bittiğinde `next_index` doluysa aynı çağrıyı tekrarlayın; tamamlanmış formüller zaten atlanır.
5. `LATEX_MISMATCH` sonucu MathMagic'in formülü yanlış dönüştürdüğü anlamına gelir. LaTeX'i düzeltip aynı işaretçiyle tekrar çalıştırın.
6. Kontrol için `mathmagic_list_equations` ve sayfa önizlemesini kullanın. İşaretçileri `remove_markers=true` ile ya da sonunda `cleanup_marker` ile kaldırın.

## Bilinen sınırlar (deneme sürümü ve ortam)

- **Lisans ("Try" modu):**
  - Her yeni MathMagic süreci lisans penceresi açar. Eklenti bağımsız süreci kullanmaz, kendi sürecini açar.
  - Bazı EPS'lerde soluk bir "Demo" filigranı olur.
  - Toplu dönüştürme (File > Convert, ileride en hızlı yol olacak) yalnızca lisansla çalışır: *"Trial version does not support this feature"*.
- **PDF dışa aktarma:** Mevcut Helvetica Neue stilinde PDF dışa aktarma MathMagic'in kendi hatasıyla başarısız oluyor. Times New Roman stilinde PDF dışa aktarma test edilmedi.
- **Odak:**
  - Eklenti yolu her formülde pencereleri öne getirir.
  - MathMagic, Claude öndeyken başlatılırsa lisans penceresi öne gelebilir.
- **"Edit Equation" bayrağı:** Eklenti başka bir MathMagic oturumunu beklerken bu bayrak tüm formüllerde kapalı görünür. Bu yüzden doğrulama, EPS içindeki MMF formül verisini esas alır.
- **Taşmış metin:** Taşmış (overset) metindeki formüllerde eklentinin taban çizgisi ayarı uygulanamaz; değer EPS başlığından hesaplanır.
