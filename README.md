# BIST Radar

BIST hisseleri için açıklanabilir karar-destek, tarama, backtest ve paper-trading sistemi. Gerçek emir göndermez; `TRADING_MODE=live` başlangıçta reddedilir.

## Mimari ve güvenlik

Akış: Provider → doğrulama/kalite → özellikler → piyasa rejimi → Radar Score → risk → sinyal → paper ledger → bildirim. Ham veri doğrulanmadan skora girmez. Eski, çelişkili, eksik veya düşük kaliteli veri; geçersiz stop ya da 2.0 altı R/R `NO_SIGNAL` üretir. UTC saklanır, sunum takviminde `Europe/Istanbul` hedeflenir. AI sayısal hesaplarda kullanılmaz.

## Kurulum

Python 3.11 ile geliştirme uyumludur; container Python 3.12 kullanır.

```bash
make install
make seed
make check
cp .env.example .env  # güçlü bir POSTGRES_PASSWORD belirleyin
docker compose up -d --build
curl http://127.0.0.1:8765/health
```

Compose yalnızca `bist-radar-network` ve `bist-radar-postgres-data` oluşturur. API sadece loopback'te yayınlanır. Port doluysa `.env` içinde `API_PORT` değiştirin. `make down` yalnızca bu compose projesini durdurur ve volume silmez.

## Yapılandırma

Tüm örnekler `.env.example` dosyasındadır. Varsayılanlar: veri kalitesi 90, risk/işlem %0.75, minimum R/R 2.0, komisyon 10 bps, slippage 5 bps. Secret'lar `.env` içinde kalır ve loglanmaz.

## API

`GET /health`, `/ready`, `/symbols`, `/radar`, `/radar/{symbol}`, `/signals`, `/paper/trades`, `/paper/performance`, `/system/status`. Yanıtlarda paper-mode ve yatırım tavsiyesi olmadığı vurgulanır. Swagger: `/docs`.

## Provider ekleme

Piyasa verisi için `MarketDataProvider`, KAP için `KapProvider`, takas için `TakasProvider` sınıfını uygulayın ve dependency injection ile servise verin. HTML scraping production sağlayıcısı değildir. Licensed provider ağ hatalarında sınırlı retry/backoff uygulamalı, sonra `PROVIDER_DOWN` dönmelidir. İkinci piyasa kaynağı fiyat toleransı aşınca `DATA_CONFLICT` üretmelidir. KAP ham metni değişmeden saklanır; takas yoksa `TAKAS_DATA_UNAVAILABLE` normal durumdur.

Telegram token yokken `MockTelegramNotifier` kullanılır. Gerçek entegrasyon eklendiğinde token yalnız environment'tan alınmalı.

## Demo ve test

Deterministik `rally`, `flat`, `selloff`, `bad_data` ve `xu100` fixture'ları bulunur. `make check` format, Ruff, mypy, pytest ve coverage kapısını çalıştırır. Backtest sinyali kapanış `t` ile hesaplar ve girişi `t+1` açılışında yapar. Evren geçmişi sağlanmadan survivorship-bias ortadan kaldırılamaz; raporlarda bu kısıt belirtilmelidir. Split/temettü ayarı provider metadata'sıyla doğrulanmalıdır.

## Troubleshooting

- Başlangıçta live-mode hatası: `.env` içinde `TRADING_MODE=paper` yapın.
- DB hazır değil: `docker compose logs bist-radar-db`, sonra migration çalıştırın.
- Provider yok: fixture modu çalışmaya devam eder; bu production piyasa verisi değildir.
- Port çakışması: `ss -ltn` ile kontrol edip `API_PORT` değiştirin.

Bu sistem yatırım tavsiyesi değildir. Karar-destek ve paper trading amaçlıdır.
