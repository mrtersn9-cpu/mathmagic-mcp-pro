# Mimari, akış, entegrasyon sınırları

## Katmanlar

1. `server.py`: MCP / JSON-RPC 2.0 `stdio` taşıyıcısı; yalnız stdout'a protokol yanıtları yazar. `initialize`, `ping`, `tools/list`, `tools/call` desteklenir.
2. `mathmagic_mcp/protocol.py`: araç şeması, temel doğrulama, hataların MCP `isError` biçiminde dönüştürülmesi.
3. `mathmagic_mcp/engine.py`: LaTeX/yer tutucu doğrulama, açık onay kapıları, bir işlem kilidi, audit log, opsiyonel manifest.
4. `mathmagic_mcp/indesign.py`: Windows COM `InDesign.Application` ve `DoScript(jsx, 1246973031)`; yalnız paket içinde tanımlı ExtendScript eylemlerine izin verilir.
5. `mathmagic_mcp/windows_ui.py`: **yalnız MathMagic Pro 9.31 InD.exe** penceresine, gerçek yürütülebilir dosya yolu eşleşiyorsa komut gönderir.

## İşlem yaşam döngüsü

- `inspect` ile belge ve MathMagic menü eylemlerinin varlığı denetlenir.
- InDesign MCP veya `jsx_select_marker()` metin imlecini seçer.
- Ayrı COM iş parçacığı, MathMagic'in `New Equation` / `Edit Equation` menü eylemini çağırır.
- MathMagic editörü açılırsa hedef süreç doğrulanır, LaTeX panoya aktarılır, `Ctrl+V`, `Shift+Enter`, `Ctrl+S` uygulanır.
- COM isteği bitse de bitmese de işlem `SUBMITTED_UNVERIFIED` sayılır. Gerekli editlenebilirlik ve matematiksel doğruluk denetimi **manuel** yapılır.

## Neden COM ve ayrı iş parçacığı?

MathMagic eklentisi dış editörü açtığında InDesign'ın menü eylemi dış uygulamayı bekleyebilir. Tek iş parçacığında `DoScript` bitmeden klavye komutu gönderilemez. Bu nedenle COM bir iş parçacığında çağrılırken UI kontrolü asıl iş akışından ilerler. COM çağrısı takılırsa süreç `daemon` iş parçacığıdır ve `timeout` ile raporlanır; sistem bu durumda kendini otomatik olarak başarılı saymaz.

## InDesign ile ortak çalışma kuralı

Bir uygulamayı iki farklı MCP sürücüsü paylaşıyor. Bu paket yalnız kendi işlem kilidini uygular. Mevcut InDesign MCP işbirliği yapıp aynı adlandırılmış sistem kilidini edinmediği sürece **çapraz MCP atomik işlem garantisi yoktur**. Operasyon sırasında diğer MCP'nin seçim/değişiklik komutlarını çağırmayın.

## İşaretçi modeli

- InDesign MCP belgeye `[[MM:Q001]]` gibi benzersiz metinler yerleştirir.
- `mathmagic_create_equation` işaretin **başlangıç ekleme noktasına** geçer, oraya formülü eklemeyi dener.
- İşaret **kendiliğinden silinmez**; editlenebilir formül kontrolünden sonra kullanıcı onayıyla kaldırılır.
- Böylece başarısız veya kısmi işlemler tespit edilebilir, bir etiket kaybolup işlem yarım kalmaz.

## İyileştirme için teknik keşif planı

- Hedef Windows makinede `inspect` çıktısından MathMagic menü eylemi ID/ad eşleşmesini kesinleştirmek.
- Native MathMagic EPS/ilintili öğe etiketini, link dosya uzantısını ve nesne çift tıklama davranışını incelemek.
- MathMagic'in varsa belgelenmiş COM/CLI arayüzünü üreticiden istemek; bulunursa UI katmanını adapter üzerinden kaldırmak.
- MathMagic penceresini olay tabanlı UI Automation ile tespit edip `SendInput` yerine uygun denetim API'sini kullanmak.
- Gözlemlenebilir durumla `VERIFIED_NATIVE_EQUATION` durumunu sadece kanıt oluştuğunda vermek.
- Regresyon testlerini MathMagic 9.31 ve InDesign 2026 Windows VM üzerinde yürütmek.

## Sınırlamalar

- Windows dışı sistemlerde uygulama entegrasyonu yoktur.
- Genel amaçlı `.InDesignPlugin` (native SDK) veya UXP paneli bu kaynak pakette bulunmaz. Zaten kurulu **resmî MathMagic eklentisi** kullanılır.
- Uygulamanın önü kapalı veya kilitli ekran oturumunda tuşlar güvenilir değildir.
- Eşzamanlı iki InDesign MCP arasında global lock yoktur.
- Vendor API olmadığı için 100'lerce formüllük tam gözetimsiz dönüşüm teslim edilmiş sayılmaz.