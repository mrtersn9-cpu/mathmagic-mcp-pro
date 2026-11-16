# MathMagic MCP Pro v0.3 — Kullanım Kılavuzu

Giriş noktası: `server_pro.py` (Claude yapılandırmasında `mathmagic-mcp-pro`).
Varsayılan mod: **offline** (`MATHMAGIC_DEFAULT_MODE`).

## Ne kullanır, ne kullanmaz

- **Kullanır:** MathMagic'e pencere mesajları (`WM_CHAR`, `WM_COMMAND`, `WM_SETTEXT`), InDesign COM'da sabit JSX betikleri, `PrintWindow` ile ekran görüntüsü.
- **Kullanmaz:** Klavye, fare, pano, `SetFocus`/`SetForegroundWindow`.
- **Dokunmaz:** Lisans penceresi ve orijinal belgelerin kaydı.
- **Otomatik kapatır:** Yalnızca MathMagic yazı tipi (PostScript adı) uyarısı ve "Tip of the Day".
- **Durur:** Lisans penceresi, tanınmayan bir modal pencere, eksik işaretçi ya da kapalı InDesign durumunda.

## İki ekleme yolu

| Mod | Nasıl | Hız (canlı ölçüm) | Odak |
|---|---|---|---|
| `offline` (varsayılan) | MathMagic EPS üretir (Save As mesajla doldurulur) → InDesign işaretçiye `place()` → gömme → eklentinin "Default Baseline" ayarı | ~1,2–1,8 sn/formül (bazıları ~3,4 sn) | Sizin uygulamanızı öne almaz |
| `plugin` | Eklentinin New/Edit Equation eylemi → MathMagic bağlı pencere (mesajla) → Update | ~2–3,5 sn/formül | Eklenti her formülde MathMagic'i, sonra InDesign'ı öne getirir |

Her iki yolda da sonuç, eklentinin "Edit Equation" ile tanıdığı, gömülü bir MathMagic EPS'sidir.

## Araçlar (19)

**Salt okunur**
- `mathmagic_policy`, `mathmagic_preflight`, `mathmagic_status`, `mathmagic_inspect_indesign`
- `mathmagic_probe_uia`
- `mathmagic_preview_equation`, `mathmagic_preview_batch`
- `mathmagic_verify_equation`, `mathmagic_capture_editor`

**Değişiklik yapanlar (`confirm=true` gerekir)**
- `mathmagic_create_equation`, `mathmagic_edit_equation`
- `mathmagic_render_eps`, `mathmagic_place_eps`
- `mathmagic_run_batch`, `mathmagic_prepare_offline_batch`
- `mathmagic_launch`, `mathmagic_dismiss_dialogs`
- `mathmagic_backup_indd`, `mathmagic_cleanup_marker`

## Soru bankası iş akışı

1. Mevcut InDesign MCP ile formül yerlerine `[[MM:Q0001]]` gibi işaretçiler koyun.
2. Bir manifest hazırlayın: `{"equations":[{"id":"Q0001","marker":"[[MM:Q0001]]","latex":"\\frac{3}{4}"}, ...]}`. En fazla 2000 formül olabilir.
3. Kaydedilmiş belgeyi yedekleyin: `mathmagic_backup_indd`.
4. Manifesti kontrol edin: `mathmagic_preview_batch`.
5. Toplu işi başlatın: `mathmagic_run_batch(confirm=true, time_budget_s=300)`. Bitmezse `start_index=next_index` ile devam edin. İlk hatada durur.
6. Örnekleyerek kontrol edin: `mathmagic_verify_equation` ve sayfa önizlemesi. Gerekirse `mathmagic_edit_equation` kullanın.
7. İşaretçileri kaldırın: `remove_marker(s)=true` ya da `mathmagic_cleanup_marker`. Bu adım yalnızca doğrulanmış formül varsa çalışır.

## Bilinen sınırlar

- **Deneme ("Try") modu:**
  - MathMagic her açılışta lisans penceresi gösterir.
  - Bazı EPS çıktılarına soluk bir **"Demo" filigranı** ekler; bu çıktılarla baskı yapılmamalıdır.
  - Lisans girildikten sonra bu durumların ortadan kalkması beklenir, yeniden test edilmelidir.
- **MathMagic'in çıkması:** MathMagic InD sürümü son belge kapanınca çıkar. Araç bu yüzden bir çalışma belgesini açık tutar; MathMagic belgelerini kapatmayın.
- **Yazı tipi:** MathMagic stil setindeki "Helvetica Neue" yazı tipi uyarı üretir ve formüller gövde metninden farklı bir yazı tipiyle dizilir. MathMagic'te StyleSet'i kitap yazı tipinize göre ayarlayın.
- **İntegral üssü:** `\int ... x^2` içindeki üssü MathMagic yüksek yerleştiriyor. Bu MathMagic'in boşluk ayarı (Define Spacing) meselesidir.
- **"Convert to Equation":** Eklentideki bu eylem betikten her durumda devre dışı görünüyor; kullanılmıyor.
- **Paralel düzenleme:** İki MCP arasında ortak kilit yok. Toplu iş sürerken InDesign MCP ile aynı belgeyi düzenlemeyin.
