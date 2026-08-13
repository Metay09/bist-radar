# Dinamik BIST Tüm Evreni

BIST Radar'ın birincil araştırma evreni artık sabit BIST 100 dosyası değildir. Borsa İstanbul'un işlem gören şirketler sayfasından yönlendirdiği KAP pazar sicili günlük okunur. Yıldız, Ana, Alt, Yakın İzleme, Piyasa Öncesi İşlem Platformu ve Gözaltı pazarlarındaki pay kodları kabul edilir. Fon, yapılandırılmış ürün, emtia ve borçlanma aracı pazarları pay evrenine alınmaz. Belirsiz veya kesin sembol kurallarına uymayan kayıtlar sessizce eşlenmez.

Her snapshot kaynak zamanı ve SHA-256 kimliğiyle saklanır. Yeni paylar `NEW_SYMBOL`, kaynaktan çıkan eski paylar `INACTIVE` olarak izlenir; geçmiş bar, sinyal, sonuç ve işlem kayıtları silinmez. Canonical sembolden Yahoo araştırma sembolüne dönüşüm yalnız `<SYMBOL>.IS` biçimindedir; fuzzy eşleme yoktur.

## Güvenli işletim

Önce yalnız ayrıştırma ve sınıflandırma yapan dry-run çalıştırın:

```bash
python -m app.cli universe-discover --dry-run
```

Worker günlük refresh yapar. Resmî sicil geçici olarak erişilemezse son başarılı snapshot korunur ve refresh başarısızlığı ayrı kaydedilir. 15 dakikalık veri güncellemesi iki günlük kontrollü overlap ile idempotent upsert kullanır. Tek sembol/batch hatası diğer sonuçları silmez; kapsam `/universe/summary` ve `/universe/failures` üzerinden görünür.

Ucuz Stage A kontrolü minimum geçmiş, güncellik/veri doğrulama ve bar aktivitesini değerlendirir. Hacim ve fiyat ivmesi birlikte keskin biçimde yükselmişse erken hareket override'ı uygulanabilir. Stage A Radar puanını değiştirmez; yalnız full Radar hesaplamasına girecek veriyi seçer. Yetersiz geçmiş `LIMITED_HISTORY`, zayıf aktivite `LIQUIDITY_FILTER` olarak audit edilir.

## Sınırlar

Yahoo/yfinance resmî Borsa İstanbul veri kaynağı değildir; sonuçlar `RESEARCH_ONLY` ve `UNVERIFIED_SOURCE` niteliğindedir. Ücretsiz provider bazı sembolleri desteklemeyebilir veya gecikmeli olabilir. Kapsam yüzde 100 değilse sistem bunu açıkça gösterir; eksik sembolü başka payla eşlemez. Uzun tarihsel intraday backfill operasyonal güncellemeden ayrı tutulmalı ve provider limitleri nedeniyle küçük batch'lerle yürütülmelidir.
