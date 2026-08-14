import { useEffect, useMemo, useRef, useState } from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useParams,
} from "react-router-dom";
import { api } from "./api";
import type {
  Bar,
  Candidate,
  Detail,
  PaperTrade,
  Signal,
  TradePlan,
} from "./types";

const trNumber = (n: number, d = 2) =>
  new Intl.NumberFormat("tr-TR", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  }).format(n);
const trDate = (v: string | null | undefined) =>
  v
    ? new Intl.DateTimeFormat("tr-TR", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(v))
    : "Veri yok";
const labels: Record<string, string> = {
  VERY_STRONG_CANDIDATE: "Çok Güçlü Aday",
  STRONG_CANDIDATE: "Güçlü Aday",
  CANDIDATE: "Aday",
  WATCH: "İzle",
  NO_SIGNAL: "Sinyal Yok",
  GIRIS_BEKLENIYOR: "Alım İçin Bekle",
  GIRIS_BOLGESINDE: "Uygun Alım Bölgesinde",
  BREAKOUT_ONAYI: "Kırılım Gerçekleşti",
  KACMIS_KOVALAMA: "Geç Kalındı - Alma",
  GECERSIZ: "İşlem Uygun Değil",
  HEALTHY: "Çalışıyor",
  RESEARCH_ONLY: "Araştırma Verisi",
  CLOSED: "Piyasa Kapalı",
  OPEN: "Piyasa Açık",
  IDLE: "Bekliyor",
  UNKNOWN: "Bilinmiyor",
  DEGRADED: "Sorunlu",
  OUTCOME_PENDING: "Sonucu bekleniyor",
  PARTIALLY_LABELED: "Kısmen sonuçlandı",
  FULLY_LABELED: "Sonuçlandı",
  WAITING_ENTRY: "Alım bölgesi bekleniyor",
  NO_ENTRY: "Alım gerçekleşmedi",
  ENTRY_ACTIVE: "İşlem aktif",
  STOPPED: "Stop oldu",
  H1_ACTIVE: "H1 görüldü · takipte",
  H2_ACTIVE: "H2 görüldü · takipte",
  H3_REACHED: "H3 gerçekleşti",
  EXPIRED_H0: "Süre doldu · hedef yok",
  EXPIRED_H1: "Süre doldu · H1",
  EXPIRED_H2: "Süre doldu · H2",
  PLAN_UNAVAILABLE: "Eski plan · doğrulanamaz",
  MODEL_READY: "Model hazır",
  ENTRY_AWARE_LOGISTIC: "Giriş duyarlı olasılık modeli",
};
const trLabel = (v: string | null | undefined) =>
  labels[v || ""] || v?.replaceAll("_", " ") || "Veri yok";
const planLabel = (plan?: TradePlan) => {
  if (!plan) return "İşlem Uygun Değil";
  if (plan.stale && !plan.market_closed)
    return "Güncel veri yok — plan uygulanabilir değil";
  if (!plan.stale && !plan.market_closed) return trLabel(plan.status);
  const prefix = "Son tamamlanmış veriye göre";
  return (
    {
      BREAKOUT_ONAYI: `${prefix} kırılım`,
      GIRIS_BOLGESINDE: `${prefix} alım bölgesinde`,
      KACMIS_KOVALAMA: `${prefix} giriş bölgesi aşılmış`,
      GIRIS_BEKLENIYOR: "Yeni alım koşulu bekleniyor",
      GECERSIZ: "İşlem Uygun Değil",
    }[plan.status] || trLabel(plan.status)
  );
};
const nav = [
  ["/", "⌁", "Radar"],
  ["/signals", "◫", "Sinyaller"],
  ["/portfolio", "◉", "Portföy"],
  ["/analysis", "⌗", "Analiz"],
  ["/system", "⚙", "Sistem"],
];
const tourSteps = [
  [
    "BIST Radar’a hoş geldiniz",
    "Doğrulanmamış araştırma verileriyle çalışan açıklanabilir karar-destek ve paper trading ürünüdür.",
  ],
  [
    "Radar ekranı",
    "Tamamlanmış barlardan çıkan güçlü adayları, veri yaşını ve piyasa bağlamını tek yerde gösterir.",
  ],
  [
    "Radar puanı",
    "0–100 bileşik puandır; yüksek puan otomatik alım emri değildir.",
  ],
  [
    "Sinyaller",
    "Geçmiş adayları, skor gelişimini ve sonuç etiketlerinin durumunu izlersiniz.",
  ],
  [
    "İşlem planı",
    "Tek al fiyatı yerine giriş bölgesi, breakout, stop ve hedefleri birlikte değerlendirin.",
  ],
  [
    "Paper Portföy",
    "Gerçek emir olmadan sanal işlemleri ve gerçekleşen performansı gösterir.",
  ],
  [
    "Analiz",
    "Skor grupları ve sinyal sonuçlarını örneklem büyüklüğüyle birlikte inceler.",
  ],
  [
    "Shadow Intelligence",
    "ML yalnız diagnostic tahmin üretir; Radar, risk veya işlem kararını değiştiremez.",
  ],
  [
    "Sistem",
    "Provider, API, veritabanı, worker ve outcome tracker sağlığını gösterir.",
  ],
  [
    "Research / Paper Only",
    "Bu sistem yatırım tavsiyesi değildir. Gecikmeli veriyle gerçek emir göndermez.",
  ],
];

function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    load()
      .then((x) => live && setData(x))
      .catch(() => live && setError("Veri servisine ulaşılamıyor"));
    return () => {
      live = false;
    };
    // Custom hook callers define the reload boundary explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error };
}
const badge = (c: string) =>
  c.includes("VERY")
    ? "positive"
    : c.includes("STRONG")
      ? "blue"
      : c === "CANDIDATE"
        ? "amber"
        : "neutral";
const planTone = (s: string) =>
  s === "GECERSIZ" || s === "KACMIS_KOVALAMA"
    ? "danger"
    : s === "BREAKOUT_ONAYI" || s === "GIRIS_BOLGESINDE"
      ? "positive"
      : "blue";

function Shell() {
  const [tour, setTour] = useState(
    () => localStorage.getItem("bist-radar-tour-seen") !== "1",
  );
  return (
    <div className="shell">
      <aside className="desktop-sidebar">
        <Brand />
        <Navigation />
        <button className="help" onClick={() => setTour(true)}>
          ⓘ Yardım / Rehber
        </button>
        <div className="legal">
          RESEARCH / PAPER ONLY
          <br />
          Yatırım tavsiyesi değildir.
        </div>
      </aside>
      <main>
        <AdaptiveDecisionCard />
        <AdaptiveAnalytics />
        <Routes>
          <Route path="/" element={<Radar />} />
          <Route path="/symbol/:symbol" element={<Stock />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/system" element={<System />} />
        </Routes>
      </main>
      <Bottom />
      <button
        className="floating-help"
        aria-label="Rehberi aç"
        onClick={() => setTour(true)}
      >
        ?
      </button>
      {tour && (
        <Tour
          onClose={() => {
            localStorage.setItem("bist-radar-tour-seen", "1");
            setTour(false);
          }}
        />
      )}
    </div>
  );
}

function AdaptiveDecisionCard() {
  const location = useLocation();
  const match = location.pathname.match(/^\/symbol\/([^/]+)$/);
  const symbol = match?.[1] || "";
  const result = useLoad(
    () => (symbol ? api.adaptive(symbol) : Promise.reject()),
    [symbol],
  );
  if (!symbol || !result.data) return null;
  const d = result.data,
    action = d.action as Record<string, unknown> | undefined,
    events = Array.isArray(d.events)
      ? (d.events as Record<string, unknown>[])
      : [],
    plans = Array.isArray(d.plans)
      ? (d.plans as Record<string, unknown>[])
      : [],
    latest = plans.at(-1)?.plan as Record<string, unknown> | undefined,
    targets = Array.isArray(latest?.targets)
      ? (latest.targets as Record<string, unknown>[])
      : [];
  return (
    <section className="adaptive-card">
      <div className="adaptive-head">
        <div>
          <span className="eyebrow">ŞU ANKİ DURUM</span>
          <h2>{trLabel(String(action?.action || d.state))}</h2>
          <p>
            {Array.isArray(action?.reason)
              ? action.reason.join(" · ")
              : trLabel(String(d.state))}
          </p>
        </div>
        <div className={`health health-${String(d.health).toLowerCase()}`}>
          <small>Setup sağlığı</small>
          <b>{String(d.health)}</b>
        </div>
      </div>
      <div className="adaptive-levels">
        <Metric
          label="Alım"
          value={
            latest
              ? `${trNumber(Number(latest.entry_zone_low))}–${trNumber(Number(latest.entry_zone_high))}`
              : "—"
          }
        />
        <Metric
          label="Aktif stop"
          value={
            d.active_stop == null
              ? latest
                ? trNumber(Number(latest.stop_price))
                : "—"
              : trNumber(Number(d.active_stop))
          }
          tone="stop"
        />
        {targets.map((target, i) => (
          <Metric
            key={i}
            label={`H${i + 1}`}
            value={trNumber(Number(target.price))}
            tone="target"
          />
        ))}
        <Metric
          label="Plan geçerliliği"
          value={`${String((d.config as Record<string, unknown>)?.entry_ttl_bars || "—")} bar`}
        />
      </div>
      <div className="action-meta">
        <span>Geçerli: {trDate(String(action?.valid_until || ""))}</span>
        <span>
          Sonraki inceleme: {trDate(String(action?.next_review || ""))}
        </span>
        <span>Policy: {String(d.policy_version)}</span>
      </div>
      <details className="adaptive-timeline">
        <summary>Karar geçmişi · {events.length} olay</summary>
        {events.map((event) => (
          <div key={String(event.sequence)}>
            <time>{trDate(String(event.event_time))}</time>
            <b>{trLabel(String(event.event_type))}</b>
            <span>{trLabel(String(event.state_to))}</span>
          </div>
        ))}
      </details>
    </section>
  );
}

function AdaptiveAnalytics() {
  const location = useLocation();
  const enabled = location.pathname === "/analysis";
  const result = useLoad(
    () => (enabled ? api.adaptiveAnalytics() : Promise.reject()),
    [enabled],
  );
  if (!enabled || !result.data) return null;
  const d = result.data;
  const outcomes = (d.outcomes || {}) as Record<string, unknown>;
  return (
    <section className="panel adaptive-analytics">
      <div className="panelhead">
        <div>
          <span className="eyebrow">ADAPTIVE CHALLENGER</span>
          <h2>Setup ve işlem yaşam döngüsü</h2>
        </div>
        <span className="tag blue">{String(d.policy_version)}</span>
      </div>
      <div className="tracking-summary">
        <Metric label="Planlanan" value={Number(d.planned || 0)} />
        <Metric label="Giriş aktive" value={Number(d.entry_activated || 0)} />
        <Metric
          label="Aktivasyon"
          value={
            d.activation_rate == null
              ? "—"
              : `%${trNumber(Number(d.activation_rate) * 100, 1)}`
          }
        />
        <Metric
          label="Beklenen R · maliyet sonrası"
          value={d.expected_r == null ? "Yetersiz veri" : trNumber(Number(d.expected_r), 3)}
        />
        <Metric
          label="Medyan R"
          value={d.median_realized_r == null ? "Yetersiz veri" : trNumber(Number(d.median_realized_r), 3)}
        />
      </div>
      <div className="outcome-chips">
        {Object.entries(outcomes).map(([key, value]) => (
          <span key={key}>{trLabel(key)} · {String(value)}</span>
        ))}
      </div>
    </section>
  );
}
function Brand() {
  return (
    <div className="brand">
      <span className="mark">◎</span>
      <div>
        <b>BIST RADAR</b>
        <small>Research Intelligence</small>
      </div>
    </div>
  );
}
function Navigation() {
  return (
    <nav aria-label="Masaüstü ana navigasyon">
      {nav.map(([to, icon, label]) => (
        <NavLink key={to} to={to} end={to === ("/" as never)}>
          <span aria-hidden="true">{icon}</span>
          {label}
        </NavLink>
      ))}
    </nav>
  );
}
function Bottom() {
  return (
    <nav className="bottom" aria-label="Mobil ana navigasyon">
      {nav.map(([to, icon, label]) => (
        <NavLink
          key={to}
          to={to}
          end={to === ("/" as never)}
          aria-label={label}
        >
          <span aria-hidden="true">{icon}</span>
          <small>{label}</small>
        </NavLink>
      ))}
    </nav>
  );
}
function Tour({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(0);
  const [title, text] = tourSteps[step];
  return (
    <div
      className="tourback"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tour-title"
    >
      <section className="tour">
        <div className="tourcount">
          {step + 1} / {tourSteps.length}
        </div>
        <h2 id="tour-title">{title}</h2>
        <p>{text}</p>
        <div className="touractions">
          <button onClick={onClose}>Atla</button>
          <button disabled={step === 0} onClick={() => setStep((x) => x - 1)}>
            Geri
          </button>
          <button
            className="primary"
            onClick={() =>
              step === tourSteps.length - 1 ? onClose() : setStep((x) => x + 1)
            }
          >
            {step === tourSteps.length - 1 ? "Tamamla" : "İleri"}
          </button>
        </div>
      </section>
    </div>
  );
}
function Info({ label, text }: { label: string; text: string }) {
  return (
    <span className="info" tabIndex={0} aria-label={`${label}: ${text}`}>
      i<span role="tooltip">{text}</span>
    </span>
  );
}
function State({
  error,
  empty = false,
  text,
}: {
  error?: string;
  empty?: boolean;
  text?: string;
}) {
  if (error) return <div className="state error">⚠ {error}</div>;
  if (empty) return <div className="state">{text || "Henüz veri yok"}</div>;
  return <div className="skeleton" aria-label="Yükleniyor" />;
}
function Header({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <header className="pagehead">
      <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <span className="pill">● PAPER MODE</span>
    </header>
  );
}

const radarState = {
  query: "bist-radar-query",
  strength: "bist-radar-strength",
  scroll: "bist-radar-scroll",
};

function Radar() {
  const summary = useLoad(api.summary);
  const universe = useLoad(api.universe);
  const rows = useLoad(api.candidates);
  const plans = useLoad(api.tradePlans);
  const [query, setQuery] = useState(
    () => sessionStorage.getItem(radarState.query) || "",
  );
  const [strength, setStrength] = useState(
    () => sessionStorage.getItem(radarState.strength) || "ALL",
  );
  const restored = useRef(false);
  useEffect(() => {
    sessionStorage.setItem(radarState.query, query);
  }, [query]);
  useEffect(() => {
    sessionStorage.setItem(radarState.strength, strength);
  }, [strength]);
  useEffect(() => {
    if (restored.current || !summary.data || !rows.data) return;
    restored.current = true;
    const top = Number(sessionStorage.getItem(radarState.scroll) || 0);
    if (top > 0)
      requestAnimationFrame(() =>
        requestAnimationFrame(() =>
          window.scrollTo({ top, behavior: "instant" }),
        ),
      );
  }, [summary.data, rows.data]);
  const filtered = useMemo(
    () =>
      [...(rows.data || [])]
        .filter((x) => x.symbol.includes(query.toUpperCase()))
        .filter(
          (x) =>
            strength === "ALL" ||
            (strength === "BIST100" && x.bist100_member) ||
            x.classification === strength,
        )
        .sort(
          (a, b) =>
            b.radar_score - a.radar_score || a.symbol.localeCompare(b.symbol),
        ),
    [rows.data, query, strength],
  );
  const planMap = Object.fromEntries(
    (plans.data || []).map((x) => [x.symbol, x]),
  );
  if (!summary.data) return <State error={summary.error} />;
  const s = summary.data;
  return (
    <>
      <Header
        title="Radar"
        subtitle="BIST Tüm taranıyor · gün içi momentum ve aday görünümü"
      />
      <div className={`fresh ${s.freshness.state.toLowerCase()}`}>
        <b>{s.freshness.label}</b>
        <span>
          {s.provider} · {trDate(s.data_timestamp)}
        </span>
      </div>
      <div className="warning">
        Yahoo/yfinance verileri araştırma amaçlı ve doğrulanmamış kaynaktır.{" "}
        <b>PAPER MODE</b>
      </div>
      <section className="universe-strip">
        <b>BIST Tüm Evreni</b>
        <span>
          {universe.data?.eligible_for_radar == null
            ? "Kapsam hesaplanıyor"
            : `${String(universe.data.eligible_for_radar)} uygun hisseden tarandı · %${trNumber(Number(universe.data.coverage_percent || 0))} kapsam`}
        </span>
      </section>
      <section className="metrics">
        {[
          ["Çok Güçlü", "VERY_STRONG_CANDIDATE"],
          ["Güçlü", "STRONG_CANDIDATE"],
          ["Aday", "CANDIDATE"],
          ["İzlenen", "WATCH"],
          ["Bekleyen Sonuç", "PENDING_OUTCOMES"],
        ].map(([label, key]) => (
          <article key={key}>
            <small>{label}</small>
            <strong>{s.counts[key] ?? 0}</strong>
          </article>
        ))}
      </section>
      <section className="panel">
        <div className="panelhead">
          <div>
            <h2>
              Öne Çıkan Adaylar{" "}
              <Info
                label="Radar puanı"
                text="0–100 bileşik karar-destek puanıdır; otomatik alım değildir."
              />
            </h2>
            <p>Radar skoruna göre sıralı</p>
          </div>
          <input
            aria-label="Sembol ara"
            placeholder="Sembol ara"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div
          className="tabs universe-filters"
          role="group"
          aria-label="Radar filtresi"
        >
          {[
            ["ALL", "BIST Tüm"],
            ["BIST100", "BIST 100"],
            ["VERY_STRONG_CANDIDATE", "Çok Güçlü"],
            ["STRONG_CANDIDATE", "Güçlü"],
            ["WATCH", "Takipte"],
          ].map(([key, label]) => (
            <button
              key={key}
              className={strength === key ? "active" : ""}
              onClick={() => setStrength(key)}
            >
              {label}
            </button>
          ))}
        </div>
        {rows.error ? (
          <State error={rows.error} />
        ) : filtered.length ? (
          <CandidateList rows={filtered} plans={planMap} />
        ) : (
          <State empty />
        )}
      </section>
    </>
  );
}

function CandidateList({
  rows,
  plans = {},
}: {
  rows: Candidate[];
  plans?: Record<string, TradePlan>;
}) {
  const remember = () =>
    sessionStorage.setItem(radarState.scroll, String(window.scrollY));
  return (
    <>
      <div className="desktop-table">
        <table>
          <thead>
            <tr>
              <th>Sembol</th>
              <th>Radar</th>
              <th>Sınıf</th>
              <th>Fiyat</th>
              <th>
                RVOL{" "}
                <Info
                  label="RVOL"
                  text="Normal işlem hacmine göre mevcut hacim. Kazanç yüzdesi değildir."
                />
              </th>
              <th>Momentum</th>
              <th>Plan</th>
              <th>Veri zamanı</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.symbol}>
                <td>
                  <Link to={`/symbol/${x.symbol}`} onClick={remember}>
                    <b>{x.symbol}</b>
                  </Link>
                </td>
                <td>
                  <span className="score">{x.radar_score}</span>
                </td>
                <td>
                  <span className={`tag ${badge(x.classification)}`}>
                    {trLabel(x.classification)}
                  </span>
                </td>
                <td>{trNumber(x.price)}</td>
                <td>{trNumber(x.rvol)}x</td>
                <td>{x.early_momentum_score}</td>
                <td>
                  <PlanBadge plan={plans[x.symbol]} />
                </td>
                <td>{trDate(x.timestamp)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mobile-signals">
        {rows.map((x) => {
          const plan = plans[x.symbol];
          return (
            <article className="signal-card" key={x.symbol}>
              <Link
                className="card-link"
                aria-label={`${x.symbol} detayını aç`}
                to={`/symbol/${x.symbol}`}
                onClick={remember}
              >
                <span>
                  <strong>{x.symbol}</strong>
                  <small>{trLabel(x.classification)}</small>
                </span>
                <span
                  className="score"
                  aria-label={`Radar puanı ${x.radar_score}`}
                >
                  {x.radar_score}
                </span>
              </Link>
              <div className="candidate-facts">
                <span>
                  <small>Fiyat</small>
                  <b>{trNumber(x.price)}</b>
                </span>
                <span title="Normal işlem hacmine göre mevcut hacim">
                  <small>RVOL · hacim</small>
                  <b>{trNumber(x.rvol)}x</b>
                </span>
                <span title="Fiyat hareketinin gücü; kazanç yüzdesi değildir">
                  <small>Momentum · fiyat gücü</small>
                  <b>{x.early_momentum_score}</b>
                </span>
              </div>
              <PlanBadge plan={plan} />
              {plan?.entry_zone_low != null && (
                <details>
                  <summary>İşlem planını göster</summary>
                  <dl>
                    <dt>Alım</dt>
                    <dd>
                      {trNumber(plan.entry_zone_low!)}–
                      {trNumber(plan.entry_zone_high!)}
                    </dd>
                    <dt>Stop</dt>
                    <dd>{trNumber(plan.stop_price!)}</dd>
                    {plan.targets?.map((t, i) => (
                      <span className="detail-row" key={t.price}>
                        <dt>Hedef {i + 1}</dt>
                        <dd>{trNumber(t.price)}</dd>
                      </span>
                    ))}
                    <dt>Risk / Getiri</dt>
                    <dd>1 : {trNumber(plan.risk_reward!)}</dd>
                  </dl>
                </details>
              )}
            </article>
          );
        })}
      </div>
    </>
  );
}
function PlanBadge({ plan }: { plan?: TradePlan }) {
  return plan ? (
    <span className={`tag ${planTone(plan.status)}`}>{planLabel(plan)}</span>
  ) : (
    <span className="tag neutral">İşlem Uygun Değil</span>
  );
}

function TradePlanCard({ plan }: { plan: TradePlan }) {
  if (plan.reference_price == null)
    return (
      <section className="panel trade-plan">
        <h2>İşlem Planı</h2>
        <State empty text={plan.explanation[0] || "Henüz yeterli bağlam yok"} />
      </section>
    );
  const targets = plan.targets || [];
  const unavailable = Boolean(plan.stale && !plan.market_closed);
  return (
    <section className="panel trade-plan">
      <div className="panelhead">
        <div>
          <span className="eyebrow">Plan durumu</span>
          <h2>
            İşlem Planı{" "}
            <Info
              label="Giriş bölgesi"
              text="Tek bir anlık fiyat yerine kontrollü alım için izlenen fiyat aralığıdır."
            />
          </h2>
        </div>
        <PlanBadge plan={plan} />
      </div>
      {(plan.stale || plan.market_closed) && (
        <div className="plan-notice">
          <b>
            {unavailable
              ? "Güncel piyasa verisi alınamadığı için bu işlem planı şu anda uygulanabilir değildir."
              : "Piyasa kapalı."}
          </b>
          <span>
            Veri {trNumber(plan.data_age_minutes || 0, 0)} dk eski. Bu plan son
            tamamlanmış araştırma verisine dayanır. Piyasa açıldığında yeniden
            değerlendirilir.
          </span>
        </div>
      )}
      <div className={`plan-primary ${unavailable ? "suppressed" : ""}`}>
        <Metric
          label="Alım"
          value={`${trNumber(plan.entry_zone_low!)} – ${trNumber(plan.entry_zone_high!)}`}
        />
        <Metric
          label="Stop"
          value={`${trNumber(plan.stop_price!)}  ·  -%${trNumber(plan.stop_distance_percent!)}`}
          tone="stop"
        />
        <Metric
          label="Hedef 1"
          value={
            targets[0]
              ? `${trNumber(targets[0].price)}  ·  +%${trNumber(targets[0].return_percent)}`
              : "Veri yok"
          }
          tone="target"
        />
      </div>
      <div className="plan-secondary">
        {targets.slice(1).map((x, i) => (
          <Metric
            key={x.price}
            label={`Hedef ${i + 2}`}
            value={`${trNumber(x.price)}  ·  +%${trNumber(x.return_percent)}`}
            tone="target"
          />
        ))}
        <Metric
          label="Risk / Getiri"
          value={`1 : ${trNumber(plan.risk_reward!)}`}
        />
      </div>
      {plan.risk_reward! < 2 && (
        <div className="warning">Risk/getiri minimum eşiğin altında.</div>
      )}
      <div className="grid2">
        <ul className="reasons">
          {plan.explanation.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
        {plan.position_sizing && (
          <div className="sizing">
            <h3>
              Önerilen pozisyon boyutu <small>(paper/research)</small>
            </h3>
            <p>
              Varsayılan sermaye:{" "}
              {trNumber(plan.position_sizing.account_equity)} · İzin verilen
              risk: %{trNumber(plan.position_sizing.max_risk_percent)} /{" "}
              {trNumber(plan.position_sizing.allowed_risk_amount)} TL
            </p>
            <strong>
              {plan.position_sizing.estimated_quantity} adet · yaklaşık{" "}
              {trNumber(plan.position_sizing.suggested_position_value)} TL
            </strong>
          </div>
        )}
      </div>
      <div className="plan-disclaimer">
        RESEARCH / PAPER ONLY — Hedefler potansiyel getiridir; garanti veya
        yatırım tavsiyesi değildir.
      </div>
    </section>
  );
}
function Metric({
  label,
  value,
  tone = "",
}: {
  label: string;
  value?: number | string;
  tone?: string;
}) {
  return (
    <div className={`plan-metric ${tone}`}>
      <small>{label}</small>
      <strong>
        {typeof value === "number" ? trNumber(value) : (value ?? "Veri yok")}
      </strong>
    </div>
  );
}

function CandleChart({ bars, plan }: { bars: Bar[]; plan?: TradePlan }) {
  if (!bars.length) return <State empty />;
  const targets = plan?.targets || [],
    levels = [
      plan?.reference_price,
      plan?.entry_zone_low,
      plan?.entry_zone_high,
      plan?.stop_price,
      ...targets.map((x) => x.price),
    ].filter((x): x is number => x != null),
    w = 900,
    h = 320,
    plot = 720,
    min = Math.min(...bars.map((x) => x.low), ...levels),
    max = Math.max(...bars.map((x) => x.high), ...levels),
    pad = (max - min) * 0.08,
    y = (v: number) =>
      22 + ((max + pad - v) / (max - min + pad * 2 || 1)) * (h - 44),
    step = plot / bars.length;
  const label = (name: string, value: number, kind: string) => (
    <g className={`level-label ${kind}`} key={`${name}-${value}`}>
      <rect x={plot + 10} y={y(value) - 11} width="154" height="22" rx="7" />
      <text x={plot + 18} y={y(value) + 4}>
        {name} {trNumber(value)}
      </text>
    </g>
  );
  return (
    <div
      className="chart"
      aria-label="Mum grafiği ve fiyat etiketli işlem planı seviyeleri"
    >
      <svg viewBox={`0 0 ${w} ${h}`} role="img">
        <rect
          className="entry-band"
          x="0"
          y={y(plan?.entry_zone_high || 0)}
          width={plot}
          height={Math.max(
            3,
            y(plan?.entry_zone_low || 0) - y(plan?.entry_zone_high || 0),
          )}
        />
        {bars.map((b, i) => {
          const x = i * step + step / 2,
            up = b.close >= b.open;
          return (
            <g key={b.timestamp} className={up ? "up" : "down"}>
              <line x1={x} y1={y(b.high)} x2={x} y2={y(b.low)} />
              <rect
                x={x - Math.max(1, step * 0.28)}
                y={Math.min(y(b.open), y(b.close))}
                width={Math.max(2, step * 0.56)}
                height={Math.max(1, Math.abs(y(b.open) - y(b.close)))}
              />
            </g>
          );
        })}
        {plan?.reference_price && (
          <>
            <line
              className="referenceline"
              x1="0"
              x2={plot}
              y1={y(plan.reference_price)}
              y2={y(plan.reference_price)}
            />
            {label("Referans", plan.reference_price, "reference")}
          </>
        )}
        {plan?.stop_price && (
          <>
            <line
              className="stopline"
              x1="0"
              x2={plot}
              y1={y(plan.stop_price)}
              y2={y(plan.stop_price)}
            />
            {label("Stop", plan.stop_price, "stop")}
          </>
        )}
        {plan?.entry_zone_low && label("Alım", plan.entry_zone_low, "entry")}
        {targets.map((x, i) => (
          <g key={x.price}>
            <line
              className={`targetline target-${i + 1}`}
              x1="0"
              x2={plot}
              y1={y(x.price)}
              y2={y(x.price)}
            />
            {label(`Hedef ${i + 1}`, x.price, `target target-${i + 1}`)}
          </g>
        ))}
      </svg>
      <div className="chartlegend">
        Grafikte yalnız backend tarafından sağlanan fiyat ve işlem planı
        seviyeleri gösterilir.
      </div>
    </div>
  );
}

function Stock() {
  const { symbol = "" } = useParams();
  const result = useLoad(() => api.detail(symbol), [symbol]);
  const results = useLoad(() => api.symbolResults(symbol), [symbol]);
  const shadow = useLoad(() => api.symbolShadow(symbol), [symbol]);
  const [tab, setTab] = useState("plan");
  if (!result.data) return <State error={result.error} />;
  const d: Detail = result.data,
    c = d.candidate,
    m = d.universe_metadata;
  return (
    <>
      <Header
        title={d.symbol}
        subtitle="Hisse detay, işlem planı ve sinyal gelişimi"
      />
      <div className={`fresh ${d.freshness.state.toLowerCase()}`}>
        {d.freshness.label}
      </div>
      {m && (
        <section className="universe-strip">
          <b>
            {m.universe} · {m.market || "Pay Piyasası"}
          </b>
          <span>
            {m.provider} ·{" "}
            {m.provider_status === "AVAILABLE"
              ? "Veri mevcut"
              : trLabel(m.provider_status)}
          </span>
        </section>
      )}
      <div className="tabs" role="tablist">
        {[
          ["plan", "İşlem Planı"],
          ["overview", "Teknik Bakış"],
          ["chart", "Grafik"],
          ["history", "Sinyal Geçmişi"],
          ["outcomes", "Sonuçlar"],
          ["shadow", "Shadow"],
        ].map(([key, label]) => (
          <button
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "active" : ""}
            onClick={() => setTab(key)}
            key={key}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "overview" && (
        <section className="metrics">
          {[
            ["Fiyat", c ? trNumber(c.price) : "Veri yok"],
            ["Radar", c ? `${c.radar_score}/100` : "Veri yok"],
            ["Sınıf", c ? trLabel(c.classification) : "Veri yok"],
            ["RVOL", c ? `${trNumber(c.rvol)}x` : "Veri yok"],
            [
              "Veri Kalitesi",
              c ? `${trNumber(c.data_quality, 0)}/100` : "Veri yok",
            ],
          ].map(([a, b]) => (
            <article key={a}>
              <small>{a}</small>
              <strong className="compact">{b}</strong>
            </article>
          ))}
        </section>
      )}
      {tab === "plan" && <TradePlanCard plan={d.trade_plan} />}{" "}
      {tab === "chart" && (
        <section className="panel">
          <h2>15 Dakikalık Fiyat</h2>
          <CandleChart bars={d.bars} plan={d.trade_plan} />
        </section>
      )}
      {tab === "history" && (
        <section className="panel">
          <h2>Sinyal Gelişimi</h2>
          {d.progression.length ? (
            <div className="timeline">
              {d.progression.map((x) => (
                <div key={x.signal_id}>
                  <time>{trDate(x.timestamp)}</time>
                  <b>{x.radar_score}</b>
                  <span>{trLabel(x.disposition || x.lifecycle)}</span>
                </div>
              ))}
            </div>
          ) : (
            <State empty />
          )}
        </section>
      )}
      {tab === "outcomes" && (
        <section className="panel">
          <h2>Sonuçlar</h2>
          {results.data?.length ? (
            <div className="history-list">
              {results.data.map((s) => (
                <SignalHistory key={s.signal_id} signal={s} />
              ))}
            </div>
          ) : (
            <State
              empty
              text="Bu sembol için henüz persisted Radar sinyali yok."
            />
          )}
        </section>
      )}
      {tab === "shadow" && (
        <section className="panel shadow">
          <h2>
            SHADOW INTELLIGENCE{" "}
            <Info
              label="Shadow"
              text="Bu model Radar kararını, riski veya işlemi değiştiremez."
            />
          </h2>
          {shadow.data ? (
            <dl>
              <dt>Radar sinyali</dt>
              <dd>{String(shadow.data.observations ?? 0)}</dd>
              <dt>Etiketli gözlem</dt>
              <dd>{String(shadow.data.labeled ?? 0)}</dd>
              <dt>Eğitime uygun</dt>
              <dd>{String(shadow.data.training_eligible ?? 0)}</dd>
              <dt>Model</dt>
              <dd>{String(shadow.data.current_model ?? "Henüz yok")}</dd>
              <dt>Durum</dt>
              <dd>{String(shadow.data.status ?? "Bilinmiyor")}</dd>
              <dt>Neden</dt>
              <dd>
                {Array.isArray(shadow.data.reasons)
                  ? shadow.data.reasons.join(" · ")
                  : "—"}
              </dd>
            </dl>
          ) : (
            <State error={shadow.error} />
          )}
        </section>
      )}
    </>
  );
}
function Signals() {
  const [bucket, setBucket] = useState("");
  const [status, setStatus] = useState("");
  const query = () => {
    const p = new URLSearchParams();
    if (bucket) p.set("score_bucket", bucket);
    if (status) p.set("status", status);
    const value = p.toString();
    return value ? `?${value}` : "";
  };
  const result = useLoad(() => api.signals(query()), [bucket, status]);
  const daily = useLoad(api.daily);
  const days = Array.isArray(daily.data) ? daily.data : [];
  const latest = days[0] || {};
  return (
    <>
      <Header
        title="Sinyal Takibi"
        subtitle="Alım aktivasyonundan stop ve hedeflere kadar kronolojik, denetlenebilir sonuçlar"
      />
      <section className="tracking-summary">
        <Metric label="Toplam sinyal" value={Number(latest.total || 0)} />
        <Metric label="Alım gerçekleşti" value={Number(latest.entered || 0)} />
        <Metric label="Alım olmadı" value={Number(latest.no_entry || 0)} />
        <Metric label="Stop" value={Number(latest.stopped || 0)} />
        <Metric
          label="H1 / H2 / H3"
          value={`${String(latest.h1_hits || 0)} / ${String(latest.h2_hits || 0)} / ${String(latest.h3_hits || 0)}`}
        />
      </section>
      <div className="method-note">
        <b>Ölçüm kuralı</b>
        <span>
          İlk 8 mumda alım bandı aranır. Girişten sonra 16 mum izlenir. Aynı
          mumdaki stop/hedef belirsizliğinde stop önce kabul edilir.
        </span>
      </div>
      <div className="tabs" aria-label="İşlem sonucu filtresi">
        {[
          ["", "Tümü"],
          ["WAITING_ENTRY", "Alım bekliyor"],
          ["ENTRY_ACTIVE", "Aktif"],
          ["NO_ENTRY", "Alım olmadı"],
          ["STOPPED", "Stop"],
          ["H3_REACHED", "H3"],
        ].map(([key, label]) => (
          <button
            key={key || "all-status"}
            className={status === key ? "active" : ""}
            onClick={() => setStatus(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="tabs" aria-label="Radar skoru filtresi">
        {["", "90+", "80-89", "70-79"].map((x) => (
          <button
            key={x || "all-score"}
            className={bucket === x ? "active" : ""}
            onClick={() => setBucket(x)}
          >
            {x || "Tüm skorlar"}
          </button>
        ))}
      </div>
      <section className="panel">
        {!result.data ? (
          <State error={result.error} />
        ) : result.data.length ? (
          <div className="history-list">
            {result.data.map((s) => (
              <SignalHistory key={s.signal_id || `${s.symbol}-${s.timestamp}`} signal={s} />
            ))}
          </div>
        ) : (
          <State empty text="Bu filtrelerle eşleşen işlem planı yok." />
        )}
      </section>
    </>
  );
}
function SignalHistory({ signal: s }: { signal: Signal }) {
  const outcome = (h: string) => s.outcomes?.[h];
  const pct = (v: unknown) =>
    typeof v === "number" ? `%${trNumber(v * 100)}` : "—";
  const audit = s.audit || {};
  const prediction = s.shadow_prediction || {};
  const quality = (prediction.head_quality || {}) as Record<
    string,
    Record<string, unknown>
  >;
  const shadowValue = (head: string, value: unknown) => {
    if (typeof value !== "number") return "—";
    return quality[head]?.display === "PROBABILITY"
      ? `%${trNumber(value * 100, 1)}`
      : `Skor ${trNumber(value * 100, 0)}/100`;
  };
  const plan = s.trade_plan_snapshot;
  const state = String(
    audit.result_classification || s.lifecycle || "OUTCOME_PENDING",
  );
  const level = (hit: unknown, terminal = false) =>
    hit
      ? `Gerçekleşti · ${trDate(String(hit))}`
      : terminal
        ? "Ulaşılmadı"
        : "Takip sürüyor";
  const terminal = Boolean(audit.terminal_at);
  return (
    <article className="history-card professional">
      <div className="trade-head">
        <div>
          <Link to={`/symbol/${s.symbol}`}>
            <strong>{s.symbol}</strong>
          </Link>
          <span
            className={`tag ${state === "STOPPED" ? "danger" : state.includes("H3") ? "positive" : "blue"}`}
          >
            {trLabel(state)}
          </span>
        </div>
        <span className="score">{s.radar_score}</span>
      </div>
      <p>
        {trDate(s.signal_timestamp || s.timestamp)} · Referans{" "}
        {trNumber(s.reference_price ?? s.price)} ·{" "}
        {trLabel(s.radar_class || s.classification)}
      </p>
      {plan ? (
        <>
          <div className="execution-path">
            <div
              className={
                audit.entry_hit_at ? "done" : terminal ? "missed" : "active"
              }
            >
              <small>1 · ALIM</small>
              <b>
                {trNumber(plan.entry_zone_low!)}–
                {trNumber(plan.entry_zone_high!)}
              </b>
              <span>
                {audit.entry_hit_at
                  ? `Gerçekleşti · ${trDate(String(audit.entry_hit_at))}`
                  : state === "NO_ENTRY"
                    ? "Pencere kapandı · gerçekleşmedi"
                    : "8 mumluk pencere açık"}
              </span>
            </div>
            <div className={audit.stop_hit_at ? "stopped" : "muted-step"}>
              <small>2 · STOP</small>
              <b>{trNumber(plan.stop_price!)}</b>
              <span>
                {audit.entry_hit_at
                  ? level(audit.stop_hit_at, terminal)
                  : "Alım sonrası izlenir"}
              </span>
            </div>
            {(plan.targets || []).map((t, i) => (
              <div
                className={
                  audit[`target${i + 1}_hit_at`] ? "done" : "muted-step"
                }
                key={t.price}
              >
                <small>
                  {i + 3} · H{i + 1}
                </small>
                <b>{trNumber(t.price)}</b>
                <span>
                  {audit.entry_hit_at
                    ? level(audit[`target${i + 1}_hit_at`], terminal)
                    : "Alım sonrası izlenir"}
                </span>
              </div>
            ))}
          </div>
          {s.shadow_prediction && (
            <div className="prediction-strip">
              <b>Shadow model · calibration kapılı</b>
              <span>Alım {shadowValue("entry", prediction.entry_probability)}</span>
              <span>Stop-before-H1 {shadowValue("stop", prediction.stop_probability)}</span>
              <span>H1 {shadowValue("h1", prediction.h1_probability)}</span>
              <span>H2|H1 {shadowValue("h2", prediction.h2_probability)}</span>
              <span>H3|H2 {shadowValue("h3", prediction.h3_probability)}</span>
            </div>
          )}
        </>
      ) : (
        <p>
          Bu eski sinyalde sabit işlem planı bulunmadığı için giriş/stop/hedef
          sonucu üretilmedi.
        </p>
      )}
      <details className="market-outcomes">
        <summary>Piyasa hareketi ayrıntıları</summary>
        <div className="outcome-grid">
          {[
            ["+15 dk", "15m"],
            ["+30 dk", "30m"],
            ["+60 dk", "60m"],
            ["+120 dk", "120m"],
            ["Gün sonu", "EOD"],
            ["Ertesi gün", "NEXT_DAY"],
          ].map(([l, h]) => (
            <Metric key={h} label={l} value={pct(outcome(h)?.forward_return)} />
          ))}
        </div>
      </details>
    </article>
  );
}
function Portfolio() {
  const result = useLoad(api.performance);
  const trades = useLoad(api.trades);
  const d = result.data;
  const rows = trades.data || [];
  return (
    <>
      <Header
        title="Paper Portföy"
        subtitle="Açık ve kapanmış sanal işlemler"
      />
      <div className="warning">
        <b>PAPER ONLY</b> — Gerçek emir veya broker bağlantısı yoktur.
      </div>
      {!d ? (
        <State error={result.error} />
      ) : (
        <section className="metrics">
          {[
            ["Gerçekleşen K/Z", d.realized_pnl],
            ["Açık Pozisyon", d.open_positions],
            ["Kapalı İşlem", d.closed_trades],
            ["Güncel Portföy", d.mtm_equity ?? "Veri yok"],
          ].map(([a, b]) => (
            <article key={String(a)}>
              <small>{String(a)}</small>
              <strong>{typeof b === "number" ? trNumber(b) : String(b)}</strong>
            </article>
          ))}
        </section>
      )}
      <TradeSection
        title="Açık Pozisyonlar"
        rows={rows.filter((x) => !x.exit_time)}
      />
      <TradeSection
        title="Kapalı İşlemler"
        rows={rows.filter((x) => Boolean(x.exit_time))}
      />
    </>
  );
}
function TradeSection({ title, rows }: { title: string; rows: PaperTrade[] }) {
  const empty = title.startsWith("Açık")
    ? "Henüz gerçek Radar paper işlemi yok. Uygun sinyaller oluştuğunda sanal işlemler burada izlenecek."
    : "Henüz kapanmış gerçek Radar paper işlemi yok.";
  return (
    <section className="panel">
      <h2>{title}</h2>
      {rows.length ? (
        <div className="trade-list">
          {rows.map((t) => (
            <article key={t.trade_id}>
              <div className="trade-head">
                <b>{t.symbol}</b>
                <span className="tag neutral">
                  {t.exit_time ? "Kapandı" : "Açık"}
                </span>
              </div>
              <dl>
                <dt>Giriş</dt>
                <dd>{trNumber(t.entry_price)}</dd>
                <dt>Adet</dt>
                <dd>{trNumber(t.position_size, 0)}</dd>
                <dt>Maliyet</dt>
                <dd>{trNumber(t.entry_price * t.position_size)} TL</dd>
                <dt>Stop</dt>
                <dd>{trNumber(t.stop_price)}</dd>
                <dt>Hedef 1</dt>
                <dd>{trNumber(t.target_1)}</dd>
                <dt>Hedef 2</dt>
                <dd>{trNumber(t.target_2)}</dd>
                {t.exit_time && (
                  <>
                    <dt>Çıkış</dt>
                    <dd>{trNumber(t.exit_price || 0)}</dd>
                    <dt>Gerçekleşen K/Z</dt>
                    <dd>{trNumber(t.net_return)} TL</dd>
                    <dt>Çıkış nedeni</dt>
                    <dd>{trLabel(t.exit_reason)}</dd>
                  </>
                )}
              </dl>
              {!t.exit_time && (
                <p>
                  Güncel araştırma fiyatı yoksa gerçekleşmemiş K/Z uydurulmaz.
                </p>
              )}
            </article>
          ))}
        </div>
      ) : (
        <State empty text={empty} />
      )}
    </section>
  );
}
function Analysis() {
  const ml = useLoad(api.ml);
  const acc = useLoad(api.accuracy);
  const ready = Number(ml.data?.training_eligible || 0) > 0;
  return (
    <>
      <Header
        title="Öğrenme ve Doğrulama"
        subtitle="Giriş, stop ve hedef olasılıklarını yalnız sonuçlanmış gerçek planlardan öğrenir"
      />
      <section className="analysis-summary">
        <Metric
          label="Toplam Radar sinyali"
          value={Number(ml.data?.observations || 0)}
        />
        <Metric
          label="Temiz eğitim örneği"
          value={Number(ml.data?.training_eligible || 0)}
        />
        <Metric
          label="Üretilen tahmin"
          value={Number(ml.data?.predictions || 0)}
        />
      </section>
      <section className="panel shadow">
        <div className="panelhead">
          <div>
            <h2>
              Shadow model{" "}
              <Info
                label="Shadow"
                text="Tahminler ölçülür ancak Radar puanını veya paper işlemi otomatik değiştirmez."
              />
            </h2>
            <p>
              16 teknik özellik · 5 olasılık başlığı · kronolojik 60/20/20 ayrım
              · 16 örnek embargo.
            </p>
          </div>
          <span
            className={`tag ${ml.data?.model_type === "ENTRY_AWARE_LOGISTIC" ? "positive" : "amber"}`}
          >
            {trLabel(
              String(ml.data?.model_type || ml.data?.status || "Bilinmiyor"),
            )}
          </span>
        </div>
        {!ml.data ? (
          <State error={ml.error} />
        ) : !ready ? (
          <div className="state compact-state">
            Giriş duyarlı sonuçlar birikiyor; eğitim eşiği henüz oluşmadı.
          </div>
        ) : (
          <dl className="learning-grid">
            <dt>Model</dt>
            <dd>{String(ml.data.current_model ?? "Henüz yok")}</dd>
            <dt>Örnek olgunluğu</dt>
            <dd>{trLabel(String(ml.data.sample_maturity ?? "Bilinmiyor"))}</dd>
            <dt>Eğitime uygun / eşik</dt>
            <dd>
              {String(ml.data.training_eligible)} /{" "}
              {String(ml.data.training_threshold)}
            </dd>
            <dt>Son başarılı eğitim</dt>
            <dd>{trDate(ml.data.last_successful_training as string)}</dd>
          </dl>
        )}
        <div className="method-note">
          <b>Güvenlik sınırı</b>
          <span>
            Model olasılık üretir; yeterli out-of-sample kanıt ve açık promotion
            kararı olmadan Radar seçimlerini değiştirmez.
          </span>
        </div>
      </section>
      <section className="panel">
        <h2>Skor Grupları · gözlenen plan sonuçları</h2>
        {!acc.data ? (
          <State error={acc.error} />
        ) : acc.data.length ? (
          <div className="bucket-grid">
            {acc.data.map((x, i) => (
              <article key={String(x.bucket ?? i)}>
                <h3>{String(x.bucket ?? "Grup")}</h3>
                <dl>
                  <dt>Sinyal</dt>
                  <dd>{String(x.unique_signals ?? 0)}</dd>
                  <dt>120 dk olgun</dt>
                  <dd>{String(x.mature_signals ?? 0)}</dd>
                  <dt>H1</dt>
                  <dd>
                    {x.h1_hit_rate == null
                      ? "—"
                      : `%${trNumber(Number(x.h1_hit_rate) * 100)}`}
                  </dd>
                  <dt>H2</dt>
                  <dd>
                    {x.h2_hit_rate == null
                      ? "—"
                      : `%${trNumber(Number(x.h2_hit_rate) * 100)}`}
                  </dd>
                  <dt>H3</dt>
                  <dd>
                    {x.h3_hit_rate == null
                      ? "—"
                      : `%${trNumber(Number(x.h3_hit_rate) * 100)}`}
                  </dd>
                  <dt>Stop önce</dt>
                  <dd>
                    {x.stop_first_rate == null
                      ? "—"
                      : `%${trNumber(Number(x.stop_first_rate) * 100)}`}
                  </dd>
                </dl>
              </article>
            ))}
          </div>
        ) : (
          <State empty text="Henüz sonuçlanan plan yok." />
        )}
      </section>
    </>
  );
}
function System() {
  const sys = useLoad(api.system);
  const sum = useLoad(api.summary);
  const universe = useLoad(api.universe);
  const jobs = Array.isArray(sys.data?.worker_jobs)
    ? (sys.data.worker_jobs as Record<string, unknown>[])
    : [];
  const scan = jobs.find((x) => String(x.job_name).includes("scan"));
  const newData = !sum.data
    ? "UNKNOWN"
    : !sum.data.market_open
      ? "MARKET_CLOSED"
      : sum.data.freshness.state === "STALE"
        ? "STALE"
        : "FRESH";
  const newDataText = {
    MARKET_CLOSED: "Yeni veri beklenmiyor — piyasa kapalı.",
    STALE: "Yeni veri gecikiyor.",
    FRESH: "Yeni veri akışı normal.",
    UNKNOWN: "Veri durumu bilinmiyor.",
  }[newData];
  return (
    <>
      <Header title="Sistem" subtitle="BIST Radar çalışma durumu" />
      <section className="panel system-board">
        <Status label="API" value={sys.error ? "DEGRADED" : "HEALTHY"} />
        <Status
          label="Veritabanı"
          value={String(sys.data?.database || "UNKNOWN")}
        />
        <Status
          label="Veri Kaynağı"
          value={String(sum.data?.provider_health || "UNKNOWN")}
        />
        <Status
          label="Piyasa"
          value={sum.data?.market_open ? "OPEN" : "CLOSED"}
        />
        <Status
          label="Otomatik Tarama"
          value={String(scan?.status || "IDLE")}
        />
        <div className="status status-wide">
          <span>Yeni piyasa verisi</span>
          <b className="muted">{newDataText}</b>
        </div>
        <div className="time-status">
          <span>
            <small>Son veri güncelleme</small>
            <b>{trDate(sum.data?.last_data_update)}</b>
          </span>
          <span>
            <small>Son provider denemesi</small>
            <b>{trDate(sum.data?.last_provider_attempt)}</b>
          </span>
          <span>
            <small>Son Radar taraması</small>
            <b>{trDate(sum.data?.last_scan)}</b>
          </span>
          <span>
            <small>Veri zamanı</small>
            <b>{trDate(sum.data?.data_timestamp)}</b>
          </span>
        </div>
      </section>
      <UniverseSummary data={universe.data} />
      <section className="panel">
        <h2>Operasyon Güvenliği</h2>
        <p>
          Yalnız araştırma ve paper trading. Canlı işlem kapalıdır; Shadow karar
          vermez.
        </p>
      </section>
    </>
  );
}
function UniverseSummary({ data }: { data?: Record<string, unknown> }) {
  const cells = [
    ["Aktif paylar", data?.total_active_equities],
    ["Verisi alınabilen", data?.provider_available],
    ["Güncel", data?.fresh],
    ["Radar’a uygun", data?.eligible_for_radar],
    [
      "Kapsama",
      data?.coverage_percent == null
        ? "Veri yok"
        : `%${trNumber(Number(data.coverage_percent))}`,
    ],
  ];
  return (
    <section className="panel">
      <h2>BIST Tüm Evreni</h2>
      <div className="metrics">
        {cells.map(([label, value]) => (
          <article key={String(label)}>
            <small>{String(label)}</small>
            <strong>{value == null ? "Veri yok" : String(value)}</strong>
          </article>
        ))}
      </div>
      {Number(data?.provider_unavailable || 0) > 0 && (
        <p>
          {String(data?.provider_unavailable)} sembolde Yahoo verisi alınamadı.
        </p>
      )}
      {Number(data?.limited_history || 0) > 0 && (
        <p>
          {String(data?.limited_history)} sembolde full Radar için henüz yeterli
          15 dakikalık geçmiş yok.
        </p>
      )}
    </section>
  );
}
function Status({ label, value }: { label: string; value: string }) {
  return (
    <div className="status">
      <span>{label}</span>
      <b className={["HEALTHY", "OPEN"].includes(value) ? "ok" : "muted"}>
        {trLabel(value)}
      </b>
    </div>
  );
}
export default function App() {
  return <Shell />;
}
