import streamlit as st
import pandas as pd
from pathlib import Path
import google.generativeai as genai
import hashlib
import matplotlib.pyplot as plt
import matplotlib
import numpy as np
import io

from licenta import (
    GEMINI_API_KEY,
    extract_category_from_text,
    serpapi_search,
    agent_analist,
    lens,
    enrich_visual_matches_with_prices,
    is_blacklisted,
    is_ro_result
)

from randare import generate_visual_response
from database import (
    init_db, save_search, save_top5_offers,
    query_offers, get_stats, get_categories, get_sources
)

matplotlib.use("Agg")

# Initializeaza baza de date la pornire
try:
    init_db()
except Exception as _db_err:
    st.warning(f"DB init: {_db_err}")

# =========================
# CONFIG STREAMLIT
# =========================
genai.configure(api_key=GEMINI_API_KEY)

st.set_page_config(
    page_title="Comparator virtual de prețuri bazat pe Inteligența Artificială",
    layout="centered",
)

st.title("Comparator virtual de prețuri bazat pe Inteligența Artificială")


# =========================
# SESSION STATE
# =========================
if "shown_df" not in st.session_state:
    st.session_state.shown_df = pd.DataFrame()

if "offset" not in st.session_state:
    st.session_state.offset = 0

if "upload_counter" not in st.session_state:
    st.session_state.upload_counter = 0


# =========================
# FUNCȚIE LINKURI CLICKABLE
# =========================
def make_clickable(df: pd.DataFrame) -> str:
    df = df.copy()

    if "Imagine" not in df.columns:
        df["Imagine"] = ""

    if "Link ofertă" not in df.columns:
        df["Link ofertă"] = ""

    df["Imagine"] = df["Imagine"].apply(
        lambda x: f'<img src="{x}" width="80">' if isinstance(x, str) and x else ""
    )

    df["Link ofertă"] = df["Link ofertă"].apply(
        lambda x: f'<a href="{x}" target="_blank">Vezi oferta</a>'
        if isinstance(x, str) and x else ""
    )

    if "Preț" in df.columns:
        df["Preț"] = df["Preț"].apply(lambda x: f"{float(x):.2f} Lei" if pd.notna(x) else "")

    if "category" in df.columns:
        df = df.drop(columns=["category"])
        
    if "Sursa" in df.columns:
        df = df.drop(columns=["Sursa"])

    return df.to_html(escape=False, index=False)


# =========================================================
# SYNC imagine între tab-uri
# =========================================================
uploaded_price_img = st.session_state.get("price_img")

if uploaded_price_img is not None:
    img_bytes = uploaded_price_img.getvalue()
    base_id = hashlib.md5(img_bytes).hexdigest()

    if st.session_state.get("last_uploaded_base_id") != base_id:
        st.session_state.upload_counter += 1
        st.session_state.last_uploaded_base_id = base_id
        st.session_state.last_uploaded_image = img_bytes
        st.session_state.last_uploaded_image_id = (
            f"{base_id}_{st.session_state.upload_counter}"
        )


# =========================
# TABURI
# =========================
tab1, tab2, tab3, tab4 = st.tabs([
    "💰 Comparator de prețuri",
    "🔍 Explorare produs",
    "📊 Analiză AI",
    "🗄️ Istoric & Query"
])


# =========================================================
# TAB 1 – COMPARATOR DE PREȚURI
# =========================================================
with tab1:

    st.subheader("💰 Comparator de prețuri")

    mode = st.radio("Alege metoda:", ["📸 Produs din imagine", "⌨️ Produs scris"])

    # =========================================================
    # 📸 PRODUS DIN IMAGINE
    # =========================================================
    if mode == "📸 Produs din imagine":

        img = st.file_uploader(
            "Atașează imaginea produsului",
            type=["jpg", "jpeg", "png"],
            key="price_img",
        )

        if img:

            img_bytes = img.getvalue()
            img_path = Path("price_input.jpg")
            img_path.write_bytes(img_bytes)

            st.image(img, width=300)

            # 🔥 Reset dacă se schimbă imaginea
            img_hash = hashlib.md5(img_bytes).hexdigest()
            if st.session_state.get("last_price_hash") != img_hash:
                st.session_state.pop("lens_data", None)
                st.session_state.pop("lens_results", None)
                st.session_state.pop("price_df", None)
                st.session_state.last_price_hash = img_hash

            # ===============================
            # 🔘 BUTON ANALIZĂ
            # ===============================
            if st.button("🔍 Analizează produsul"):

                with st.spinner("🔍 Analizez imaginea cu Google Lens..."):
                    lens_data = lens(str(img_path))

                st.session_state.lens_data = lens_data

            # ===============================
            # 🔥 CONTINUĂ DOAR DACĂ EXISTĂ ANALIZĂ
            # ===============================
            if "lens_data" in st.session_state:

                if "lens_results" not in st.session_state:
                    
                    lens_data = st.session_state.lens_data
                if "lens_results" not in st.session_state:
                    visual_matches = lens_data.get("visual_matches", [])
                    total_received_val = len(visual_matches)

                    if not visual_matches:
                        st.session_state.lens_results = "empty_lens"
                    else:

                        with st.spinner("💸 Completez prețurile lipsă..."):
                            visual_matches = enrich_visual_matches_with_prices(
                                visual_matches,
                                sleep_s=1.2,
                                only_ro=False,
                            )

                        # ===============================
                        # FILTRARE
                        # ===============================
                        eliminated_non_ro = 0
                        eliminated_blacklist = 0
                        eliminated_category = 0
                        eliminated_no_price = 0
                        eliminated_invalid_price = 0
                        
                        rows = []

                        first_title = visual_matches[0].get("title", "")
                        detected_category = extract_category_from_text(first_title)

                        for item in visual_matches:

                            link = item.get("link")

                            if not is_ro_result(link, item.get("source")):
                                eliminated_non_ro += 1
                                continue

                            if is_blacklisted(link, item.get("source")):
                                eliminated_blacklist += 1
                                continue

                            p = item.get("_price_final")

                            if not p or (isinstance(p, dict) and p.get("error")):
                                eliminated_no_price += 1
                                continue

                            price_val = p.get("value")

                            if not isinstance(price_val, (int, float)):
                                eliminated_invalid_price += 1
                                continue

                            rows.append(
                                {
                                    "position": item.get("position"),
                                    "title": item.get("title"),
                                    "price": float(price_val),
                                    "source": item.get("source"),
                                    "link": link,
                                    "image": item.get("thumbnail"),
                                    "in_stock": p.get("in_stock"),
                                    "via": p.get("via"),
                                    "category": detected_category
                                }
                            )

                        df = pd.DataFrame(rows)

                        # ===============================
                        # FILTRARE STATISTICĂ ±70%
                        # ===============================
                        eliminated_statistical = 0

                        if not df.empty:
                            before_stat = len(df)

                            median_price = df["price"].median()
                            lower_bound = median_price * 0.3
                            upper_bound = median_price * 1.7

                            df = df[
                                (df["price"] >= lower_bound) &
                                (df["price"] <= upper_bound)
                            ]

                            eliminated_statistical = before_stat - len(df)

                        if df.empty:
                            st.session_state.lens_results = {
                                "cloudinary_url": lens_data.get("cloudinary_url"),
                                "total_received": total_received_val,
                                "accepted_offers": 0,
                                "eliminated_total": eliminated_total,
                                "acceptance_rate": 0,
                                "eliminated_stats": {
                                    "non_ro": eliminated_non_ro,
                                    "blacklist": eliminated_blacklist,
                                    "category": eliminated_category,
                                    "no_price": eliminated_no_price,
                                    "invalid_price": eliminated_invalid_price,
                                    "statistical": eliminated_statistical
                                },
                                "df_display": pd.DataFrame(),
                                "raw_df": pd.DataFrame(),
                                "first_title": first_title,
                                "analysis": None,
                                "empty_filtered": True
                            }
                        else:

                            df = df.sort_values("position").reset_index(drop=True)

                            # Pregătim dataframe-ul pentru afișare (traducere coloane)
                            df_display = df.copy()

                            df_display["in_stock"] = df_display["in_stock"].map(
                                {
                                    True: '<span style="color:green; font-weight:bold;">În stoc</span>',
                                    False: '<span style="color:red; font-weight:bold;">Indisponibil</span>',
                                    None: '<span style="color:gray;">—</span>',
                                }
                            )

                            if "position" in df_display.columns:
                                df_display = df_display.drop(columns=["position"])

                            df_display = df_display.rename(columns={
                                "title": "Denumire",
                                "price": "Preț",
                                "source": "Magazin",
                                "link": "Link ofertă",
                                "image": "Imagine",
                                "in_stock": "Disponibilitate",
                                "via": "Sursa"
                            })

                            accepted_offers = len(df)

                            eliminated_total = (
                                eliminated_non_ro +
                                eliminated_blacklist +
                                eliminated_category +
                                eliminated_no_price +
                                eliminated_invalid_price +
                                eliminated_statistical
                            )

                            acceptance_rate = round((accepted_offers / total_received_val) * 100, 1)
                            
                            # ── Salvare automata top 5 in baza de date
                            try:
                                detected_cat = (
                                    df["category"].iloc[0]
                                    if "category" in df.columns and not df.empty
                                    else None
                                )
                                sid = save_search(
                                    search_type="image",
                                    image_path=str(img_path),
                                    detected_category=detected_cat,
                                )
                                save_top5_offers(sid, df, detected_category=detected_cat)
                            except Exception:
                                pass

                            st.session_state.lens_results = {
                                "cloudinary_url": lens_data.get("cloudinary_url"),
                                "total_received": total_received_val,
                                "accepted_offers": accepted_offers,
                                "eliminated_total": eliminated_total,
                                "acceptance_rate": acceptance_rate,
                                "eliminated_stats": {
                                    "non_ro": eliminated_non_ro,
                                    "blacklist": eliminated_blacklist,
                                    "category": eliminated_category,
                                    "no_price": eliminated_no_price,
                                    "invalid_price": eliminated_invalid_price,
                                    "statistical": eliminated_statistical
                                },
                                "df_display": df_display,
                                "raw_df": df,
                                "first_title": first_title,
                                "analysis": None
                            }

                # ===============================
                # AFIȘARE DIN CACHE
                # ===============================
                if "lens_results" in st.session_state:
                    res = st.session_state.lens_results

                    if res == "empty_lens":
                        st.warning("Google Lens nu a returnat rezultate.")
                    else:
                        if res.get("empty_filtered"):
                            st.warning("Nu au rămas oferte valide după filtrare. Iată de ce:")
                        else:
                            st.write("Cloudinary URL:", res["cloudinary_url"])
                        
                        st.markdown("## 📊 Analiza procesului de filtrare")
                        col1, col2, col3, col4 = st.columns(4)

                        col1.metric("Oferte primite", res["total_received"])
                        col2.metric("Oferte acceptate", res["accepted_offers"])
                        col3.metric("Oferte eliminate", res["eliminated_total"])
                        col4.metric("Rată acceptare", f"{res['acceptance_rate']}%")

                        with st.expander("Vezi motivele eliminării"):
                            stats_l = res["eliminated_stats"]
                            st.write(f"- Magazin non-românesc: {stats_l['non_ro']}")
                            st.write(f"- Marketplace blacklist: {stats_l['blacklist']}")
                            st.write(f"- Nepotrivire categorie: {stats_l['category']}")
                            st.write(f"- Fără preț detectabil: {stats_l['no_price']}")
                            st.write(f"- Preț invalid / eronat: {stats_l['invalid_price']}")
                            st.write(f"- Eliminare statistică: {stats_l['statistical']}")

                        st.divider()

                        if not res.get("empty_filtered"):
                            st.markdown("## 📋 Oferte valide identificate")
                            st.markdown(make_clickable(res["df_display"]), unsafe_allow_html=True)

                        st.divider()

                        if res.get("analysis"):
                            st.info(res["analysis"])
                        else:
                            if st.button("Generează analiză de piață cu Agentul AI"):
                                with st.spinner("Agentul analizează ofertele..."):
                                    res["analysis"] = agent_analist(res["first_title"], res["raw_df"])
                                    st.rerun()

        else:
            # Curatam sesiunea daca imaginea e scoasa de user (click pe 'X')
            st.session_state.pop("lens_data", None)
            st.session_state.pop("lens_results", None)
            st.session_state.pop("price_df", None)
            st.session_state.pop("last_price_hash", None)

    # =========================================================
    # ⌨️ PRODUS SCRIS
    # =========================================================
    else:

        query = st.text_input("Introdu produsul")

        if query:

            # Reset dacă se schimbă textul căutat
            if st.session_state.get("last_query") != query:
                st.session_state.pop("text_results", None)
                st.session_state.last_query = query

            if st.button("🔍 Analizează produsul scris"):

                with st.spinner("🔍 Caut prețuri..."):
                    df, stats = serpapi_search(query, return_stats=True)

                total_received = stats.get("total_received", 0)

                if not df.empty:
                    accepted_offers = len(df)
                    eliminated_total = total_received - accepted_offers
                    acceptance_rate = round((accepted_offers / total_received) * 100, 1) if total_received > 0 else 0

                    df_display = df.copy()
                    df_display = df_display.rename(columns={
                        "title": "Denumire",
                        "price": "Preț",
                        "currency": "Monedă",
                        "source": "Magazin",
                        "link": "Link ofertă",
                        "image": "Imagine"
                    })

                    # ── Salvare automata top 5 in baza de date
                    try:
                        detected_cat = extract_category_from_text(query)
                        sid = save_search(
                            search_type="text",
                            query_text=query,
                            detected_category=detected_cat,
                        )
                        save_top5_offers(sid, df, detected_category=detected_cat)
                    except Exception:
                        pass

                    st.session_state.text_results = {
                        "total_received": total_received,
                        "accepted_offers": accepted_offers,
                        "eliminated_total": eliminated_total,
                        "acceptance_rate": acceptance_rate,
                        "stats": stats,
                        "df_display": df_display,
                        "raw_df": df,
                        "query": query,
                        "analysis": None
                    }
                else:
                    st.session_state.text_results = "empty"

            # ===============================
            # AFIȘARE DIN CACHE
            # ===============================
            if "text_results" in st.session_state:
                res = st.session_state.text_results

                if res == "empty":
                    st.warning("Nu au fost găsite oferte.")
                else:
                    st.markdown("## 📊 Analiza rezultatelor Google Shopping")

                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Oferte identificate", res["total_received"])
                    col2.metric("Oferte acceptate", res["accepted_offers"])
                    col3.metric("Oferte eliminate", res["eliminated_total"])
                    col4.metric("Rată acceptare", f"{res['acceptance_rate']}%")

                    with st.expander("Vezi motivele eliminării"):
                        s = res["stats"]
                        st.write(f"- Fără preț detectabil: {s.get('eliminated_no_price', 0)}")
                        st.write(f"- Eliminare statistică: {s.get('eliminated_statistical', 0)}")
                        st.write(f"- Nepotrivire categorie: {s.get('eliminated_category', 0)}")
                        st.write(f"- Magazin non-românesc: {s.get('eliminated_non_ro', 0)}")
                        st.write(f"- Marketplace blacklist: {s.get('eliminated_blacklist', 0)}")

                    st.divider()

                    st.markdown("## 📋 Oferte identificate")
                    st.markdown(make_clickable(res["df_display"]), unsafe_allow_html=True)

                    st.divider()

                    if res.get("analysis"):
                        st.info(res["analysis"])
                    else:
                        if st.button("Generează analiză de piață cu Agentul AI", key="text_ai_btn"):
                            with st.spinner("Agentul analizează ofertele..."):
                                res["analysis"] = agent_analist(res["query"], res["raw_df"])
                                st.rerun()


# =========================================================
# TAB 2 – EXPLORARE PRODUS
# =========================================================
with tab2:

    st.subheader("🔍 Explorare produs – AI vizual")

    imgs = st.file_uploader(
        "📸 Încarcă una sau mai multe imagini",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key=f"explore_imgs_{st.session_state.get('last_uploaded_image_id', 'base')}",
    )

    img_paths = []
    display_items = []

    # Imagini manuale
    if imgs:
        for i, img in enumerate(imgs):
            path = Path(f"explore_input_{i}.jpg")
            path.write_bytes(img.getvalue())
            img_paths.append(str(path))
            display_items.append((img, f"Imagine adăugată {i+1}"))

    # Imagine din Comparator
    if "last_uploaded_image" in st.session_state:
        auto_img_bytes = st.session_state.last_uploaded_image
        img_id = st.session_state.get("last_uploaded_image_id", "noid")

        path_auto = Path(f"explore_auto_{img_id}.jpg")
        path_auto.write_bytes(auto_img_bytes)
        img_paths.append(str(path_auto))
        display_items.append((str(path_auto), "Imagine din Comparator"))

    # Afișare poze input pe coloane (side-by-side)
    if display_items:
        cols = st.columns(len(display_items))
        for idx, (img_src, caption) in enumerate(display_items):
            with cols[idx]:
                st.image(img_src, width=250, caption=caption)

    # Buton eliminare
    if "last_uploaded_image" in st.session_state:
        if st.button("🗑️ Elimină imaginea din Comparator"):
            st.session_state.pop("last_uploaded_image", None)
            st.session_state.pop("last_uploaded_image_id", None)
            st.session_state.pop("last_uploaded_base_id", None)
            st.rerun()

    prompt = st.text_area(
        "✍️ Spune AI-ului ce vrei să facă:",
        placeholder=(
            "Exemple:\n"
            "- Schimbă culoarea tricoului\n"
            "- Pune tricoul din imaginea 2 pe persoana din imaginea 1\n"
            "- Adaugă un fundal urban, stil realist"
        ),
    )

    if st.button("🎨 Generează simulare"):

        if not img_paths or not prompt:
            st.warning("Încarcă cel puțin o imagine și introdu un prompt.")

        else:

            with st.spinner("AI generează imaginile..."):
                results = generate_visual_response(prompt, img_paths)

            if not results:
                st.error("Nu s-au generat imagini.")
            else:

                st.success(f"{len(results)} imagini generate.")

                cols = st.columns(len(results))

                for i, img_path in enumerate(results):

                    with cols[i]:

                        st.image(img_path, use_container_width=True)

                        with open(img_path, "rb") as f:
                            st.download_button(
                                label=f"📥 Descarcă imaginea {i+1}",
                                data=f,
                                file_name=Path(img_path).name,
                                mime="image/png",
                            )


# =========================================================
# TAB 3 – ANALIZĂ AI
# =========================================================
with tab3:

    st.subheader("📊 Analiză AI – Comparație modele generative")

    # -------------------------------------------------------
    # Încărcare date
    # -------------------------------------------------------
    csv_path = Path("rezultate.csv")

    if not csv_path.exists():
        st.error("Fișierul rezultate.csv nu a fost găsit în directorul aplicației.")
        st.stop()

    df_raw = pd.read_csv(csv_path)

    # -------------------------------------------------------
    # 1. TABEL DATE BRUTE
    # -------------------------------------------------------
    st.markdown("### 📋 Date brute – toate evaluările")

    col_filter1, col_filter2 = st.columns(2)
    with col_filter1:
        modele_disponibile = ["Toate"] + sorted(df_raw["model"].unique().tolist())
        model_filter = st.selectbox("Filtrează după model:", modele_disponibile)
    with col_filter2:
        categorii_disponibile = ["Toate"] + sorted(df_raw["categorie"].unique().tolist())
        cat_filter = st.selectbox("Filtrează după categorie:", categorii_disponibile)

    df_filtered = df_raw.copy()
    if model_filter != "Toate":
        df_filtered = df_filtered[df_filtered["model"] == model_filter]
    if cat_filter != "Toate":
        df_filtered = df_filtered[df_filtered["categorie"] == cat_filter]

    st.dataframe(df_filtered, use_container_width=True, height=300)
    st.caption(f"Afișând {len(df_filtered)} din {len(df_raw)} înregistrări")

    st.divider()

    # -------------------------------------------------------
    # Pregătire date pentru grafice
    # -------------------------------------------------------
    metrici = ["respectare_cerinta", "integrare_element", "coerenta_luminii", "realism", "fidelitate"]
    df_radar = df_raw.groupby("model")[metrici].mean()

    colors_map = {'Gemini': '#1a73e8', 'Flux': '#34a853', 'Qwen': '#ea4335'}

    # -------------------------------------------------------
    # 2. RADAR CHART
    # -------------------------------------------------------
    st.markdown("### 🕸️ Grafic Radar – Profilul calitativ al modelelor")

    labels = np.array(metrici)
    num_vars = len(labels)
    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
    angles += angles[:1]

    fig_radar, ax_radar = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

    for model in df_radar.index:
        values = df_radar.loc[model].tolist()
        values += values[:1]
        color = colors_map.get(model, 'gray')
        ax_radar.plot(angles, values, color=color, linewidth=2, label=model)
        ax_radar.fill(angles, values, color=color, alpha=0.15)

    ax_radar.set_theta_offset(np.pi / 2)
    ax_radar.set_theta_direction(-1)
    ax_radar.set_xticks(angles[:-1])
    ax_radar.set_xticklabels(['Cerință', 'Integrare', 'Lumină', 'Realism', 'Fidelitate'], fontsize=11)
    ax_radar.set_ylim(0, 5)
    ax_radar.set_yticks([1, 2, 3, 4, 5])
    ax_radar.set_yticklabels(['1', '2', '3', '4', '5'], fontsize=8, color='gray')
    ax_radar.grid(color='gray', linestyle='--', linewidth=0.5, alpha=0.5)

    fig_radar.patch.set_facecolor('#0e1117')
    ax_radar.set_facecolor('#0e1117')
    ax_radar.tick_params(colors='white')
    plt.setp(ax_radar.get_xticklabels(), color='white')

    plt.title("Analiză Comparativă: Profilul Modelelor (Radar)", size=16, y=1.1, color='white')
    plt.legend(loc='upper right', bbox_to_anchor=(1.3, 1.15), labelcolor='white',
               facecolor='#1c1c2e', edgecolor='gray')
    fig_radar.tight_layout()

    buf_radar = io.BytesIO()
    fig_radar.savefig(buf_radar, format="png", dpi=150, bbox_inches="tight",
                      facecolor=fig_radar.get_facecolor())
    buf_radar.seek(0)
    st.image(buf_radar, use_container_width=True)
    plt.close(fig_radar)

    st.divider()

    # -------------------------------------------------------
    # 3. BAR CHART – EFICIENȚĂ
    # -------------------------------------------------------
    st.markdown("### ⚡ Grafic Bare – Eficiență validată (Calitate² / log(Timp))")

    df_eff = df_raw.copy()
    df_eff["eficienta_grafic"] = df_eff.apply(
        lambda x: (x["scor_total"] ** 2 / np.log1p(x["timp_executie"])) if x["scor_total"] >= 3.5 else 0,
        axis=1
    )
    eficienta_medie = df_eff.groupby("model")["eficienta_grafic"].mean().sort_values(ascending=False)

    fig_bar, ax_bar = plt.subplots(figsize=(10, 6))
    fig_bar.patch.set_facecolor('#0e1117')
    ax_bar.set_facecolor('#1c1c2e')

    bar_colors = [colors_map.get(m, 'gray') for m in eficienta_medie.index]
    bars = ax_bar.bar(eficienta_medie.index, eficienta_medie.values,
                      color=bar_colors, edgecolor='white', alpha=0.85, width=0.5)

    for i, (bar, v) in enumerate(zip(bars, eficienta_medie.values)):
        ax_bar.text(bar.get_x() + bar.get_width() / 2, v + 0.02,
                    f"{round(v, 2)}", ha='center', va='bottom',
                    color='white', fontsize=12, fontweight='bold')

    ax_bar.set_title("Eficiență Validată: Calitate² / log(Timp)", size=14, color='white', pad=15)
    ax_bar.set_xlabel("Model", color='white', fontsize=12)
    ax_bar.set_ylabel("Scor Eficiență", color='white', fontsize=12)
    ax_bar.tick_params(colors='white')
    ax_bar.spines['bottom'].set_color('gray')
    ax_bar.spines['left'].set_color('gray')
    ax_bar.spines['top'].set_visible(False)
    ax_bar.spines['right'].set_visible(False)
    ax_bar.grid(axis='y', linestyle='--', alpha=0.4, color='gray')
    ax_bar.set_xticks(range(len(eficienta_medie.index)))
    ax_bar.set_xticklabels(eficienta_medie.index, rotation=0, color='white', fontsize=12)
    fig_bar.text(0.5, -0.02, "Scor mai mare = model mai eficient",
                 ha='center', color='gray', fontsize=10)
    fig_bar.tight_layout()

    buf_bar = io.BytesIO()
    fig_bar.savefig(buf_bar, format="png", dpi=150, bbox_inches="tight",
                    facecolor=fig_bar.get_facecolor())
    buf_bar.seek(0)
    st.image(buf_bar, use_container_width=True)
    plt.close(fig_bar)

    st.divider()

    # -------------------------------------------------------
    # 4. BOX PLOT – Distribuția scorurilor totale per model
    # -------------------------------------------------------
    st.markdown("### 📦 Box Plot – Distribuția scorurilor totale per model")

    models_order = sorted(df_raw["model"].unique())
    data_box = [df_raw[df_raw["model"] == m]["scor_total"].values for m in models_order]
    box_colors = [colors_map.get(m, 'gray') for m in models_order]

    fig_box, ax_box = plt.subplots(figsize=(10, 6))
    fig_box.patch.set_facecolor('#0e1117')
    ax_box.set_facecolor('#1c1c2e')

    bp = ax_box.boxplot(data_box, patch_artist=True, notch=False,
                        medianprops=dict(color='white', linewidth=2))

    for patch, color in zip(bp['boxes'], box_colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    for element in ['whiskers', 'caps', 'fliers']:
        for item in bp[element]:
            item.set_color('white')

    ax_box.set_xticklabels(models_order, color='white', fontsize=12)
    ax_box.set_title("Distribuția scorurilor totale per model", size=14, color='white', pad=15)
    ax_box.set_xlabel("Model", color='white', fontsize=12)
    ax_box.set_ylabel("Scor total", color='white', fontsize=12)
    ax_box.tick_params(colors='white')
    ax_box.spines['bottom'].set_color('gray')
    ax_box.spines['left'].set_color('gray')
    ax_box.spines['top'].set_visible(False)
    ax_box.spines['right'].set_visible(False)
    ax_box.grid(axis='y', linestyle='--', alpha=0.4, color='gray')
    fig_box.tight_layout()

    buf_box = io.BytesIO()
    fig_box.savefig(buf_box, format="png", dpi=150, bbox_inches="tight",
                    facecolor=fig_box.get_facecolor())
    buf_box.seek(0)
    st.image(buf_box, use_container_width=True)
    plt.close(fig_box)

    st.divider()

    # -------------------------------------------------------
    # 5. HEATMAP – Medii metrice per model
    # -------------------------------------------------------
    st.markdown("### 🌡️ Heatmap – Medii metrice per model")

    heatmap_data = df_raw.groupby("model")[metrici].mean()
    labels_ro = ['Cerință', 'Integrare', 'Lumină', 'Realism', 'Fidelitate']

    fig_hm, ax_hm = plt.subplots(figsize=(10, 4))
    fig_hm.patch.set_facecolor('#0e1117')
    ax_hm.set_facecolor('#0e1117')

    im = ax_hm.imshow(heatmap_data.values, aspect='auto', cmap='RdYlGn', vmin=1, vmax=5)

    ax_hm.set_xticks(range(len(metrici)))
    ax_hm.set_xticklabels(labels_ro, color='white', fontsize=11)
    ax_hm.set_yticks(range(len(heatmap_data.index)))
    ax_hm.set_yticklabels(heatmap_data.index, color='white', fontsize=12)
    ax_hm.tick_params(colors='white')

    for i in range(len(heatmap_data.index)):
        for j in range(len(metrici)):
            val = heatmap_data.values[i, j]
            ax_hm.text(j, i, f"{val:.2f}", ha='center', va='center',
                       color='white' if val < 3.5 else 'black', fontsize=11, fontweight='bold')

    cbar = fig_hm.colorbar(im, ax=ax_hm)
    cbar.ax.yaxis.set_tick_params(color='white')
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color='white')

    ax_hm.set_title("Medii metrice calitative per model", size=14, color='white', pad=15)
    fig_hm.tight_layout()

    buf_hm = io.BytesIO()
    fig_hm.savefig(buf_hm, format="png", dpi=150, bbox_inches="tight",
                   facecolor=fig_hm.get_facecolor())
    buf_hm.seek(0)
    st.image(buf_hm, use_container_width=True)
    plt.close(fig_hm)

    st.divider()

    # -------------------------------------------------------
    # 6. BAR CHART – Timp mediu de execuție per model
    # -------------------------------------------------------
    st.markdown("### ⏱️ Timp mediu de execuție per model")

    timp_mediu = df_raw.groupby("model")["timp_executie"].mean().sort_values()

    fig_timp, ax_timp = plt.subplots(figsize=(10, 5))
    fig_timp.patch.set_facecolor('#0e1117')
    ax_timp.set_facecolor('#1c1c2e')

    bar_colors_timp = [colors_map.get(m, 'gray') for m in timp_mediu.index]
    bars_timp = ax_timp.barh(timp_mediu.index, timp_mediu.values,
                             color=bar_colors_timp, edgecolor='white', alpha=0.85, height=0.4)

    for bar, v in zip(bars_timp, timp_mediu.values):
        ax_timp.text(v + 0.3, bar.get_y() + bar.get_height() / 2,
                     f"{v:.1f}s", va='center', color='white', fontsize=11, fontweight='bold')

    ax_timp.set_title("Timp mediu de execuție per model (secunde)", size=14, color='white', pad=15)
    ax_timp.set_xlabel("Secunde", color='white', fontsize=12)
    ax_timp.tick_params(colors='white')
    ax_timp.spines['bottom'].set_color('gray')
    ax_timp.spines['left'].set_color('gray')
    ax_timp.spines['top'].set_visible(False)
    ax_timp.spines['right'].set_visible(False)
    ax_timp.grid(axis='x', linestyle='--', alpha=0.4, color='gray')
    ax_timp.set_yticklabels(timp_mediu.index, color='white', fontsize=12)
    fig_timp.tight_layout()

    buf_timp = io.BytesIO()
    fig_timp.savefig(buf_timp, format="png", dpi=150, bbox_inches="tight",
                     facecolor=fig_timp.get_facecolor())
    buf_timp.seek(0)
    st.image(buf_timp, use_container_width=True)
    plt.close(fig_timp)

    st.divider()

    # -------------------------------------------------------
    # 7. BAR CHART GRUPAT – Performanță per categorie
    # -------------------------------------------------------
    st.markdown("### 🗂️ Scor mediu per categorie și model")

    df_cat = df_raw.groupby(["categorie", "model"])["scor_total"].mean().unstack(fill_value=0)

    x = np.arange(len(df_cat.index))
    width = 0.25
    multiplier = 0

    fig_cat, ax_cat = plt.subplots(figsize=(12, 6))
    fig_cat.patch.set_facecolor('#0e1117')
    ax_cat.set_facecolor('#1c1c2e')

    for model_name in df_cat.columns:
        offset = width * multiplier
        color = colors_map.get(model_name, 'gray')
        rects = ax_cat.bar(x + offset, df_cat[model_name], width,
                           label=model_name, color=color, alpha=0.85, edgecolor='white')
        multiplier += 1

    ax_cat.set_title("Scor mediu total per categorie și model", size=14, color='white', pad=15)
    ax_cat.set_xlabel("Categorie", color='white', fontsize=11)
    ax_cat.set_ylabel("Scor mediu", color='white', fontsize=11)
    ax_cat.set_xticks(x + width)
    ax_cat.set_xticklabels(df_cat.index, rotation=20, ha='right', color='white', fontsize=9)
    ax_cat.tick_params(colors='white')
    ax_cat.spines['bottom'].set_color('gray')
    ax_cat.spines['left'].set_color('gray')
    ax_cat.spines['top'].set_visible(False)
    ax_cat.spines['right'].set_visible(False)
    ax_cat.grid(axis='y', linestyle='--', alpha=0.4, color='gray')
    ax_cat.legend(loc='lower right', facecolor='#1c1c2e', edgecolor='gray', labelcolor='white')
    ax_cat.set_ylim(0, 5.5)
    fig_cat.tight_layout()

    buf_cat = io.BytesIO()
    fig_cat.savefig(buf_cat, format="png", dpi=150, bbox_inches="tight",
                    facecolor=fig_cat.get_facecolor())
    buf_cat.seek(0)
    st.image(buf_cat, use_container_width=True)
    plt.close(fig_cat)


# =========================================================
# TAB 4 – ISTORIC & QUERY
# =========================================================
with tab4:

    st.subheader("🗄️ Istoric oferte salvate")

    # ── Dashboard statistici generale
    try:
        stats = get_stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📊 Oferte totale",  stats["total_offers"])
        c2.metric("🔍 Căutări totale", stats["total_searches"])
        c3.metric("📦 Produse unice",  stats["total_products"])
        c4.metric("🖼️ Imagini locale", stats["total_images"])

        if stats["total_offers"] > 0:
            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("Preț minim (RON)", f"{stats['price_min']:.2f}")
            cc2.metric("Preț mediu (RON)", f"{stats['price_avg']:.2f}")
            cc3.metric("Preț maxim (RON)", f"{stats['price_max']:.2f}")
    except Exception as e:
        st.warning(f"Nu pot citi statisticile: {e}")

    st.divider()

    # ── Filtre interactiv
    st.markdown("### 🔎 Filtrare oferte")

    try:
        cats_db  = [""] + get_categories()
        srcs_db  = [""] + get_sources()
    except Exception:
        cats_db  = [""]
        srcs_db  = [""]

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        sel_cat   = st.selectbox("Categorie", cats_db, key="db_cat")
        sel_src   = st.selectbox("Magazin", srcs_db, key="db_src")
        sel_avail = st.selectbox(
            "Disponibilitate",
            ["", "in_stock", "out_of_stock", "unknown"],
            key="db_avail"
        )
    with col_f2:
        sel_min = st.number_input("Preț minim (RON)", min_value=0.0,
                                   value=0.0, step=10.0, key="db_min")
        sel_max = st.number_input("Preț maxim (RON)", min_value=0.0,
                                   value=10000.0, step=100.0, key="db_max")

    if st.button("🔍 Caută în istoric", key="db_search_btn"):
        try:
            df_hist = query_offers(
                category     = sel_cat or None,
                source       = sel_src or None,
                min_price    = sel_min if sel_min > 0 else None,
                max_price    = sel_max if sel_max < 10000 else None,
                availability = sel_avail or None,
            )

            if df_hist.empty:
                st.warning("⚠️ Niciun rezultat pentru filtrele selectate.")
            else:
                st.success(f"✅ {len(df_hist)} oferte găsite")

                # Afisam imaginile locale unde exista
                df_show = df_hist.drop(columns=["Imagine locală"], errors="ignore")
                st.dataframe(df_show, use_container_width=True)

                # Preview imagini locale
                imgs_with_path = df_hist[df_hist["Imagine locală"].notna() &
                                         (df_hist["Imagine locală"] != "")]
                if not imgs_with_path.empty:
                    st.markdown("#### 🖼️ Imagini locale salvate")
                    cols_img = st.columns(min(5, len(imgs_with_path)))
                    for idx, (_, r) in enumerate(imgs_with_path.iterrows()):
                        local_p = r["Imagine locală"]
                        if local_p and Path(local_p).exists():
                            cols_img[idx % 5].image(
                                local_p,
                                caption=r.get("Magazin", ""),
                                width=120
                            )

                # Export CSV
                csv_data = df_hist.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="📥 Export CSV",
                    data=csv_data,
                    file_name="oferte_istorice.csv",
                    mime="text/csv",
                )

        except Exception as e:
            st.error(f"Eroare la interogare: {e}")

    st.divider()

    # ── Actiuni admin
    with st.expander("⚙️ Acțiuni administrare bază de date"):
        zile = st.number_input("Sterge oferte mai vechi de N zile",
                               min_value=1, value=30, key="db_zile")
        if st.button("🗑️ Sterge oferte vechi", key="db_delete_btn"):
            from database import delete_old_offers
            delete_old_offers(days=int(zile))
            st.success(f"Ofertele mai vechi de {zile} zile au fost șterse.")
            st.rerun()