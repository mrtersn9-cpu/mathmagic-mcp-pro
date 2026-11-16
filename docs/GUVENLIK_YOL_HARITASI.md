# Güvenlik, sürüm sınırları ve geliştirme yol haritası

## Mevcut güvenlik tedbirleri

- Hiçbir uzaktan endpoint, otomatik yükleme, kimlik bilgisi gereksinimi yoktur.
- `confirm=true` olmadan InDesign değişikliği yapılmaz.
- `human_verified=true` olmadan işaretçi silinmez.
- LaTeX en fazla 4000 karakter; birkaç potansiyel tehlikeli TeX komutu engellenir. **Bu kapsamlı TeX güvenlik analizinin yerini tutmaz.**
- İşaretçiler tekil ve karakter kümesi sınırlı.
- Toplu liste JSON 1 MB ve en fazla 100 iş ile sınırlı.
- Belge üzerine otomatik `save` veya `saveAs` yapılmaz.
- Doğrulanamayan adım `FAILED_OR_PARTIAL` veya `SUBMITTED_UNVERIFIED` kaydedilir.
- Dış MathMagic uygulamasının yürütülebilir dosya yolu denetlenir; genel masaüstünde rastgele pencereye yazılmaz.

## Bilinen riskler

1. Yerel UI otomasyonu eklentinin davranışına göre yanlış editör alanına yazabilir. Gerçek sistemde pilot test zorunlu.
2. Clipboard metin dışı formatları korunmayabilir.
3. İki MCP aynı InDesign belgesini aynı anda düzenlerse yarış oluşabilir.
4. `.indd` dosyası InDesign içindeyken son kaydedilen diskteki sürümle bellek sürümü farklı olabilir; dosya bazlı yedek **kaydedilmemiş** değişiklikleri almaz.
5. Windows yönetici ayrıcalıkları ve UAC farklı seviyede uygulamaları etkiler.
6. MathMagic telifli bir üründür. Kod, tersine mühendislik yapılmış kapalı kaynak bir protokol içermez.

## Gerçek ürün sürümüne geçiş için öncelikler

P0: Gerçek Windows 11 / InDesign 2026 / MathMagic 9.31 makinesinde 10 formüllük uçtan uca pilot ve yeniden düzenleme testi. Bütün menü eylemi adlarını kaydet.

P1: `pywinauto` ile odak yönetimini pencere kontrolü düzeyine indir. Her komuttan sonra uygulama durumunu okuyabilen adapter geliştir. İstisna kayıtlarını ayrıntılandır.

P2: InDesign yerel MathMagic nesnesini güvenilir tanıyabilecek `pageItem`/`link` tespitini araştır. Formülün içerik ve konumunu eşleştiren kanıt üret. Olanaklıysa editördən LaTeX tekrar dışa aktarıp doğrula.

P3: İki MCP için ortak kilit protokolü. Var olan InDesign MCP'nin çağrıları da ortak kilidi kullanmalı. Undo/rollback için belgenin saklanan sürümünden güvenli yeniden üretim tasarla.

P4: UI odağından bağımsız çalışma için MathMagic üreticisinden resmî SDK/CLI/COM/API belgeleri temin et. Mevcut değilse native C++ InDesign SDK eklentisi geliştirme fizibilitesini incele.

P5: UXP paneli veya menü eklentisi ayrı bir proje olarak eklenebilir. **Bu paketin zaten InDesign içine native eklenti kurduğu söylenmemelidir.**

## Dağıtım / güncelleme

Projeyi yalnız güvenilir kaynaklardan indirin. Paket kaynağı bilinmeyen scriptleri InDesign içinde çalıştırmaz. Üçüncü taraf Python bağımlılıklarının sürümlerini kurum içi geliştirme aşamasında sabitleyin; paylaşımlı bilgisayarlarda yerel antivirüs ve kullanıcı yetkileriyle kontrol edin.