import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import joblib
import requests
import datetime
import json
from pathlib import Path
from ollama import chat

# ==========================================
# 1. CẤU HÌNH TRANG & GIAO DIỆN MLOPS CSS
# ==========================================
st.set_page_config(page_title="AeroDelay Interactive System", page_icon="✈️", layout="wide")

st.markdown("""
    <style>
    .insight-box { background-color: #f8fbff; padding: 15px; border-left: 5px solid #0366d6; border-radius: 5px; margin-bottom: 20px; font-size: 0.95em;}
    .metric-card { background-color: #ffffff; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #e1e4e8; box-shadow: 0 2px 4px rgba(0,0,0,0.05);}
    .action-box { background-color: #f0fff4; padding: 15px; border-radius: 8px; border: 1px solid #c6f6d5; margin-bottom: 15px; }
    .llm-box { background-color: #fff8e1; padding: 15px; border-radius: 8px; border: 1px dashed #ff9800; margin-top: 15px;}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. PROMPT LLM
# ==========================================
SYSTEM_PROMPT = """
Bạn là một chuyên gia điều hành vận hành hàng không (Aviation Operations Expert).
Dựa trên bảng mã IATA Delay Codes chuẩn (AHM730) và các thông số chuyến bay được cung cấp, hãy chẩn đoán nguyên nhân gốc rễ gây trễ chuyến và gán MỘT mã IATA duy nhất, ưu tiên theo thứ tự logic nghiệp vụ sau:

[NHÓM THỜI TIẾT]
- CODE_71 (WO): Thời tiết xấu tại sân bay đi (Weather at departure). Áp dụng nếu Weather_Delay_Risk_Score cao, có rủi ro bão, mưa lớn, hoặc tầm nhìn kém.
- CODE_72 (WT): Thời tiết xấu tại điểm đến (Weather at destination). Áp dụng nếu Destination_Congestion_Risk bị ảnh hưởng bởi thời tiết hoặc có ghi chú.

[NHÓM XOAY VÒNG TÀU BAY - REACTIONARY]
- CODE_93 (RA): Trễ do xoay vòng tàu bay (Aircraft Rotation / Late arrival). Đây là nguyên nhân phổ biến nhất. Áp dụng nếu Turnaround_Buffer < 0 (tàu bay đến trễ), hoặc Accumulated_Delay lớn.

[NHÓM SÂN BAY & KHÔNG LƯU - ATC/AIRPORT]
- CODE_89 (AM): Tắc nghẽn tại sân bay đi (Restrictions at airport of departure). Áp dụng nếu Airport_Load_Factor cao (>0.85) hoặc Flight_Density_Disruption cao.
- CODE_81 (AT): Tắc nghẽn do không lưu (ATFM Restrictions). Áp dụng nếu Taxi_Out_Congestion cao hoặc tắc nghẽn dọc đường bay.
- CODE_06 (OA): Không có sẵn cổng/bãi đỗ (No gate/stand availability). Áp dụng nếu Is_Remote_Stand = 1 (phải dùng xe buýt) kết hợp tải lượng sân bay cao.

[NHÓM KHÁC]
- CODE_99 (MX): Nguyên nhân khác (Other reason). Dùng khi không có tín hiệu rõ ràng từ dữ liệu.

BẮT BUỘC trả về ĐÚNG định dạng JSON như sau, KHÔNG kèm markdown hay bất kỳ văn bản giải thích thừa nào bên ngoài:
{"Delay_Code": "CODE_XX", "Reason": "Giải thích logic dưới 30 chữ dựa trên dữ liệu đầu vào."}
"""

# Cung cấp ví dụ (Few-shot) để đưa vào ngữ cảnh của user
FEW_SHOT_CONTEXT = """
Dưới đây là một số ví dụ phân tích để bạn tham khảo:

Ví dụ 1:
Đầu vào: {"Departure_Delay": 120, "Turnaround_Buffer": -45, "Weather_Delay_Risk_Score": 0, "Airport_Load_Factor": 0.4}
Đầu ra (JSON): {"Delay_Code": "CODE_93", "Reason": "Turnaround Buffer âm 45 phút cho thấy tàu bay đến muộn từ chặng trước, gây trễ dây chuyền."}

Ví dụ 2:
Đầu vào: {"Departure_Delay": 50, "Turnaround_Buffer": 180, "Weather_Delay_Risk_Score": 0.85, "Airport_Load_Factor": 0.3}
Đầu ra (JSON): {"Delay_Code": "CODE_71", "Reason": "Chuyến bay có Weather_Delay_Risk_Score rất cao (0.85), các yếu tố vận hành khác bình thường."}

Ví dụ 3:
Đầu vào: {"Departure_Delay": 40, "Turnaround_Buffer": 60, "Weather_Delay_Risk_Score": 0, "Airport_Load_Factor": 0.96}
Đầu ra (JSON): {"Delay_Code": "CODE_89", "Reason": "Tải lượng sân bay đạt mức 96% gây tắc nghẽn cục bộ tại bãi đỗ và đường lăn."}
"""


def predict_delay_reason_local(flight_data: dict) -> dict:
    user_content = f"{FEW_SHOT_CONTEXT}\n\nPhân tích chuyến bay thực tế sau:\n{json.dumps(flight_data, ensure_ascii=False)}"
    try:
        response = chat(
            model="ministral-3:3b-cloud",
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': user_content}
            ],
            options={"temperature": 0.0, "num_predict": 150}
        )
        result_text = response.message.content.strip()

        # Tiền xử lý: Cắt bỏ các thẻ markdown ```json ``` mà LLM hay thêm vào
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()

        start_idx = result_text.find('{')
        end_idx = result_text.rfind('}')

        if start_idx != -1 and end_idx != -1:
            json_str = result_text[start_idx:end_idx + 1]
            return json.loads(json_str)
        else:
            return {"Delay_Code": "CODE_99",
                    "Reason": f"Không tìm thấy định dạng JSON. LLM trả về: {result_text[:50]}..."}

    except Exception as e:
        return {"Delay_Code": "CODE_99", "Reason": f"Lỗi gọi Model (Hãy chắc chắn Ollama đang bật): {str(e)}"}


# ==========================================
# 3. NẠP DỮ LIỆU & MÔ HÌNH HỌC MÁY THỰC TẾ
# ==========================================
@st.cache_data
def load_historical_data():
    try:
        df = pd.read_csv("Data crawl/Gold_layer/Features/master_departure_features_gold_annotated.csv")
    except FileNotFoundError:
        try:
            df = pd.read_csv("Data crawl/Gold_layer/Features/master_departure_features_gold.csv")
        except FileNotFoundError:
            st.error("🚨 Lỗi: Không tìm thấy file dữ liệu tại tầng Gold Layer!")
            st.stop()

    df['Scheduled_Time'] = pd.to_datetime(df['Scheduled_Time'], errors='coerce')
    df['Actual_Time'] = pd.to_datetime(df.get('Actual_Time', pd.Series()), errors='coerce')
    df['Hour'] = df['Scheduled_Time'].dt.hour
    df['DayOfWeek'] = df['Scheduled_Time'].dt.day_name()
    df['Airport'] = df.get('Origin', df.get('Airport', 'SGN'))
    df['Tail_Number'] = df.get('Scheduled_Tail', df.get('Tail_Number', 'Unknown'))
    df['Category'] = df.get('Category', 'passenger')

    df['Incoming_Delay'] = df.get('Prev_Departure_Delay_Tail_1', 0).fillna(0)
    df['Turnaround_Buffer_Actual'] = df.get('Turnaround_Buffer', 45 - df['Incoming_Delay']).fillna(45)
    df['Departure_Delay_Real'] = df.get('Departure_Delay_Reg_Target', df.get('Departure_Delay', 0)).fillna(0)

    if 'LLM_Delay_Code' not in df.columns:
        df['LLM_Delay_Code'] = '-1'
    return df


@st.cache_resource
def load_ml_model():
    model_path = Path("Source code/models/best_aerodelay_model.pkl")
    features_path = Path("Source code/models/best_model_features.pkl")
    if not model_path.exists():
        model_path = Path(
            "/Users/nguyenhung/PycharmProjects/DS108_AeroDelay/Source code/models/best_aerodelay_model.pkl")
        features_path = Path(
            "/Users/nguyenhung/PycharmProjects/DS108_AeroDelay/Source code/models/best_model_features.pkl")
    try:
        model = joblib.load(model_path)
        features = joblib.load(features_path)
        return model, features, True
    except Exception:
        return None, None, False


def fetch_live_weather(airport_code, query_date):
    coords = {'SGN': (10.8161, 106.6673), 'HAN': (21.2212, 105.8072), 'DAD': (16.0439, 108.2022)}
    lat, lon = coords.get(airport_code, (10.8161, 106.6673))
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=precipitation,wind_speed_10m"
        res = requests.get(url, timeout=3).json()
        precip = res.get('current', {}).get('precipitation', 0.0)
        wind = res.get('current', {}).get('wind_speed_10m', 0.0)
        risk = min(1.0, (precip / 15) + (wind / 60))
        return risk, precip, wind
    except:
        return 0.15, 0.0, 12.0


df_raw = load_historical_data()
model, model_features, model_loaded = load_ml_model()

# ==========================================
# 4. SIDEBAR (CONTROL PANEL LỌC DỮ LIỆU)
# ==========================================
st.sidebar.image("https://cdn-icons-png.flaticon.com/512/3135/3135715.png", width=50)
st.sidebar.title("AeroDelay Control")

airport_list = sorted(df_raw['Airport'].dropna().unique().tolist())
airline_list = sorted(df_raw.get('Airline', pd.Series(['Vietnam Airlines'])).dropna().unique().tolist())
default_list = ['Vietnam Airlines', 'VietJet Air', 'Vietravel Airlines', 'Bamboo Airways', 'Sun PhuQuoc Airways']

selected_airports = st.sidebar.multiselect("📍 Chọn Sân bay:", options=airport_list, default=airport_list)
selected_airlines = st.sidebar.multiselect("✈️ Chọn Hãng Khai thác:", options=airline_list, default=default_list)
delay_threshold = st.sidebar.slider("⏱️ Ngưỡng xác định Trễ (Phút):", min_value=15, max_value=60, value=15, step=5)

df_filtered = df_raw[
    (df_raw['Airport'].isin(selected_airports)) & (df_raw.get('Airline', df_raw.index).isin(selected_airlines))].copy()
df_filtered['Is_Delayed_Custom'] = df_filtered['Departure_Delay_Real'] >= delay_threshold

tab1, tab2, tab3 = st.tabs(["📊 EDA: HẠ TẦNG & KHAI THÁC", "🔄 A-CDM: TRỄ LAN TRUYỀN", "🤖 DỰ ĐOÁN TRỄ CHUYẾN"])

# ------------------------------------------
# TAB 1: EDA HẠ TẦNG SÂN BAY & VẬN HÀNH
# ------------------------------------------
with tab1:
    st.header("Dashboard Năng lực Khai thác Tại Sân bay")
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"<div class='metric-card'>Số chuyến khai thác<br><h2>{len(df_filtered):,}</h2></div>",
                unsafe_allow_html=True)
    c2.markdown(
        f"<div class='metric-card'>Số chuyến trễ (>{delay_threshold}p)<br><h2>{df_filtered['Is_Delayed_Custom'].sum():,}</h2></div>",
        unsafe_allow_html=True)
    c3.markdown(
        f"<div class='metric-card'>Tỷ lệ Trễ chuyến<br><h2>{(df_filtered['Is_Delayed_Custom'].sum() / len(df_filtered) * 100 if len(df_filtered) > 0 else 0):.1f}%</h2></div>",
        unsafe_allow_html=True)
    c4.markdown(
        f"<div class='metric-card'>Độ trễ TB (Phút)<br><h2>{df_filtered['Departure_Delay_Real'].mean():.1f}</h2></div>",
        unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    col0, col1 = st.columns([1, 1.5])
    with col0:
        st.subheader("1. Phân bổ Nguyên nhân Trễ (IATA Codes)")

        # 1. Định nghĩa bảng ánh xạ để hiển thị chi tiết (cần thiết cho Tooltip)
        delay_code_map = {
            'CODE_71': 'Thời tiết xấu tại sân bay khởi hành',
            'CODE_72': 'Thời tiết xấu tại điểm đến',
            'CODE_93': 'Trễ do xoay vòng tàu bay (RA)',
            'CODE_89': 'Tắc nghẽn tại sân bay khởi hành',
            'CODE_81': 'Hạn chế không lưu (ATFM)',
            'CODE_06': 'Thiếu cổng/bãi đỗ (No gate)',
            'CODE_99': 'Nguyên nhân khác'
        }

        # 2. Xử lý dữ liệu
        df_causes = df_filtered[~df_filtered['LLM_Delay_Code'].isin([np.nan, 'NaN', '', 'ERROR'])].copy()
        df_causes['LLM_Delay_Code'] = df_causes['LLM_Delay_Code'].replace(['-1', -1], 'Đúng giờ')

        # Loại bỏ 'Đúng giờ'
        df_causes = df_causes[df_causes['LLM_Delay_Code'] != 'Đúng giờ']

        if not df_causes.empty:
            causes_count = df_causes['LLM_Delay_Code'].value_counts().reset_index()
            causes_count.columns = ['Mã IATA', 'Số lượng']

            # Gán mô tả chi tiết vào cột mới để hiển thị trong biểu đồ
            causes_count['Mô tả'] = causes_count['Mã IATA'].map(delay_code_map).fillna('Không xác định')

            # 3. Vẽ biểu đồ với hover_data để hiện mô tả
            fig_pie = px.pie(causes_count, values='Số lượng', names='Mã IATA', hole=0.4,
                             hover_data=['Mô tả'],
                             color_discrete_sequence=px.colors.qualitative.Pastel)

            fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>Số lượng: %{value}<br>Mô tả: %{customdata[0]}")
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("Hiện không có chuyến bay trễ trong phân khúc này.")

    with col1:
        st.subheader("2. Phân bố Lưu lượng & Tỷ lệ Trễ theo Giờ")
        hourly = df_filtered.groupby('Hour').agg(Vols=('Flight_No', 'count'),
                                                 Delay_Rate=('Is_Delayed_Custom', 'mean')).reset_index()
        hourly['Delay_Rate'] *= 100
        fig_hr = go.Figure()
        fig_hr.add_trace(go.Bar(x=hourly['Hour'], y=hourly['Vols'], name='Lưu lượng', marker_color='#aed6f1'))
        fig_hr.add_trace(go.Scatter(x=hourly['Hour'], y=hourly['Delay_Rate'], name='Tỷ lệ Trễ (%)', yaxis='y2',
                                    line=dict(color='red', width=3)))
        fig_hr.update_layout(yaxis2=dict(title='Tỷ lệ Trễ (%)', overlaying='y', side='right'))
        st.plotly_chart(fig_hr, use_container_width=True)

    st.divider()
    col3, col4 = st.columns([1.2, 1])
    with col3:
        st.subheader("3. Mạng lưới Phân bổ (AODB Treemap)")
        df_tree = df_filtered.groupby(['Airport', 'Airline']).agg(Total_Flights=('Flight_No', 'count'),
                                                                  Avg_Delay=('Departure_Delay_Real',
                                                                             'mean')).reset_index()
        fig_tree = px.treemap(df_tree, path=[px.Constant("Tất cả mạng bay"), 'Airport', 'Airline'],
                              values='Total_Flights', color='Avg_Delay', color_continuous_scale='Reds')
        st.plotly_chart(fig_tree, use_container_width=True)
        st.markdown(
            "<div class='insight-box'><b>💡 Ý nghĩa trực quan Treemap:</b> Kích thước ô đại diện cho quy mô lưu lượng cất cánh; sắc độ màu đỏ đại diện cho độ trễ tích lũy trung bình. Giúp xác định nút thắt năng lực khai thác của từng hãng tại mỗi cảng hàng không.</div>",
            unsafe_allow_html=True)

    with col4:
        st.subheader("4. Phân bổ Độ trễ theo Loại Tàu bay")
        fig_box = px.box(df_filtered[df_filtered['Is_Delayed_Custom']], x='Aircraft_Type', y='Departure_Delay_Real',
                         color='Airport',
                         labels={'Departure_Delay_Real': 'Số phút trễ thực tế', 'Aircraft_Type': 'Loại Tàu bay'})
        fig_box.update_yaxes(range=[0, 150])
        st.plotly_chart(fig_box, use_container_width=True)
        st.markdown(
            "<div class='insight-box'><b>💡 Ý nghĩa trực quan Boxplot:</b> Trực quan hóa biên độ biến động trễ cất cánh theo từng loại cấu hình tàu bay (Thân rộng vs Thân hẹp), giúp kiểm định giả thuyết về ảnh hưởng của thời gian phục vụ kỹ thuật mặt đất lên độ trễ.</div>",
            unsafe_allow_html=True)

# ------------------------------------------
# TAB 2: A-CDM TRỄ LAN TRUYỀN & ĐIỀU HÀNH
# ------------------------------------------
with tab2:
    st.markdown(
        "Kéo thanh trượt để thử nghiệm kịch bản cực đoan: Mọi chuyến bay cập bến đều bị trễ thêm X phút. Quan sát sự sụt giảm thời gian Buffer.")
    sim_added_delay = st.slider("🌪️ Giả lập: Độ trễ cộng thêm vào luồng chuyến bay ĐẾN (Incoming Delay + X phút):",
                                min_value=0, max_value=60, value=0, step=5)

    df_sim = df_filtered.copy()
    df_sim['Turnaround_Buffer_Sim'] = df_sim['Turnaround_Buffer_Actual'] - sim_added_delay
    df_sim['Delay_Category'] = np.where(df_sim['Turnaround_Buffer_Sim'] < 0, "Thâm hụt (Lan truyền)",
                                        "An toàn (Đủ Buffer)")

    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("1. Sự suy giảm Quỹ thời gian cho chặng tiếp theo (Buffer Deficit)")
        fig_hist = px.histogram(df_sim, x='Turnaround_Buffer_Sim', color='Delay_Category',
                                color_discrete_map={"Thâm hụt (Lan truyền)": '#d32f2f',
                                                    "An toàn (Đủ Buffer)": '#2e7d32'},
                                nbins=50, labels={'Turnaround_Buffer_Sim': 'Turnaround Buffer thực tế (Phút)'})
        fig_hist.update_xaxes(range=[-60, 120])
        st.plotly_chart(fig_hist, use_container_width=True)

    with c2:
        st.subheader("2. Tương quan: Trễ chặng trước và Trễ khởi hành")
        fig_scatter = px.scatter(df_sim.sample(min(2000, len(df_sim))), x='Incoming_Delay', y='Departure_Delay_Real',
                                 color='Is_Delayed_Custom', opacity=0.6,
                                 color_discrete_map={True: '#d32f2f', False: '#2e7d32'},
                                 labels={'Incoming_Delay': 'Độ trễ chặng trước (Phút)',
                                         'Departure_Delay_Real': 'Trễ cất cánh chuyến sau (Phút)'})
        fig_scatter.update_xaxes(range=[-10, 150])
        fig_scatter.update_yaxes(range=[-10, 150])
        st.plotly_chart(fig_scatter, use_container_width=True)

    st.divider()
    c3, c4 = st.columns([1, 1.5])
    with c3:
        st.subheader("3. Khả năng phục hồi Quỹ thời gian cho chặng tiếp theo theo Khung giờ")
        # Phân tích Boxplot để xem khung giờ nào dễ bị sập quỹ thời gian quay đầu (Turnaround) nhất
        fig_buffer_hr = px.box(df_filtered, x='Hour', y='Turnaround_Buffer_Actual',
                               color_discrete_sequence=['#ff9800'],
                               labels={'Hour': 'Khung giờ trong ngày (Hour)',
                                       'Turnaround_Buffer_Actual': 'Turnaround Buffer (Phút)'})

        # Thêm đường đánh dấu ngưỡng nguy hiểm (Buffer = 0)
        fig_buffer_hr.add_hline(y=0, line_dash="dash", line_color="red",
                                annotation_text="Ngưỡng thâm hụt (Buffer < 0)")
        fig_buffer_hr.update_yaxes(range=[-60, 120])
        st.plotly_chart(fig_buffer_hr, use_container_width=True)

        st.markdown(
            "<div class='insight-box'><b>💡 Insight A-CDM:</b> Biểu đồ hộp (Boxplot) cho thấy các khung giờ cao điểm có nguy cơ làm quỹ thời gian mặt đất (Buffer) lao dốc xuống dưới 0 mạnh nhất. Khi trung vị đâm xuyên qua vạch đỏ, nguy cơ trễ lan truyền hệ thống là không thể tránh khỏi.</div>",
            unsafe_allow_html=True)

    with c4:
        st.subheader("4. Tích lũy trễ theo tàu bay")
        all_tails = sorted(df_filtered['Tail_Number'].dropna().unique().tolist())
        selected_tail = st.selectbox("✈️ Chọn số đăng ký Tàu bay (Tail Number):", all_tails, index=1)

        df_tail = df_filtered[df_filtered['Tail_Number'] == selected_tail].sort_values('Scheduled_Time')

        if not df_tail.empty:
            ac_type = df_tail['Aircraft_Type'].iloc[0] if 'Aircraft_Type' in df_tail.columns else "N/A"
            fig_tail = go.Figure()
            fig_tail.add_trace(
                go.Scatter(x=df_tail['Scheduled_Time'], y=df_tail['Departure_Delay_Real'], mode='lines+markers',
                           name='Trễ Cất cánh (Phút)', marker=dict(size=10, color='red')))
            fig_tail.add_trace(
                go.Scatter(x=df_tail['Scheduled_Time'], y=df_tail['Turnaround_Buffer_Actual'], mode='lines+markers',
                           name='Turnaround Buffer', marker=dict(size=10, color='blue')))
            fig_tail.update_layout(
                title=f"Nhật ký tích lũy trễ của Tàu: {selected_tail} | Cấu hình dòng máy bay: {ac_type}")
            st.plotly_chart(fig_tail, use_container_width=True)

            # BỔ SUNG BẢNG HIỂN THỊ CÁC CHUYẾN BAY CỦA ĐUÔI TÀU ĐÓ THEO ĐÚNG 11 CỘT ĐẶC TRƯNG YÊU CẦU
            st.markdown(f"##### 📋 Danh sách lịch trình bay chi tiết của Tàu {selected_tail}:")
            req_cols = ['Scheduled_Time', 'Actual_Time', 'Destination', 'IATA', 'Airline', 'Flight_No', 'Terminal',
                        'Departure_Runway', 'Status', 'Is_Fixed_Flight', 'Category']
            existing_cols = [c for c in req_cols if c in df_tail.columns]
            st.dataframe(df_tail[existing_cols], width="stretch")

# ------------------------------------------
# TAB 3: LIVE AI PREDICTOR (BRONZE PIPELINE ENGINE)
# ------------------------------------------
with tab3:
    # Khởi tạo bộ đệm Session State để tránh lỗi trống thông tin môi trường
    if 'derived_buffer' not in st.session_state: st.session_state['derived_buffer'] = 45.0
    if 'derived_inc_delay' not in st.session_state: st.session_state['derived_inc_delay'] = 0.0
    if 'live_weather_score' not in st.session_state: st.session_state['live_weather_score'] = 0.1
    if 'live_precip' not in st.session_state: st.session_state['live_precip'] = 0.0
    if 'live_wind' not in st.session_state: st.session_state['live_wind'] = 8.0
    if 'feature_vector_df' not in st.session_state: st.session_state['feature_vector_df'] = None
    if 'prediction_minutes' not in st.session_state: st.session_state['prediction_minutes'] = 0
    if 'llm_diagnose' not in st.session_state: st.session_state['llm_diagnose'] = None

    col_in, col_out = st.columns([1, 1.3])

    with col_in:
        st.subheader("📥 Thông tin Lịch trình Chuyến bay (Bronze Inputs)")
        with st.form("bronze_input_form"):
            f_flight_no = st.text_input("Mã chuyến bay (Flight_No):", value="VN213")
            f_origin = st.selectbox("Sân bay Cất cánh (Origin):", ["SGN", "HAN", "DAD"])
            f_iata = st.text_input("Mã IATA Sân bay đến (Destination IATA):", value="HAN")
            f_date = st.date_input("Ngày bay (Date):", value=datetime.date.today())
            f_time_str = st.text_input("Giờ cất cánh dự kiến (HH:MM):", value="14:30",
                                       help="Nhập giờ theo định dạng 24 giờ. Ví dụ: 08:15, 23:00")

            # Xử lý bóc tách cấu trúc giờ an toàn để nạp vào Feature Pipeline
            try:
                f_time_parsed = datetime.datetime.strptime(f_time_str.strip(), "%H:%M").time()
                f_hour = f_time_parsed.hour
            except ValueError:
                st.sidebar.error(
                    "⚠️ Định dạng giờ nhập vào không hợp lệ (Phải là HH:MM). Hệ thống tự động đồng bộ về 12 giờ mặc định.")
                f_hour = 12
            f_runway = st.text_input("Đường băng đăng ký (Departure_Runway):", value="25R")
            f_tail = st.text_input("Số hiệu Đăng ký Tàu bay (Tail_Number):", value="VN-A321")
            f_ac_type = st.text_input("Loại máy bay khai thác (Aircraft_Type):", value="A321")

            btn_fetch = st.form_submit_button("🔄 Thu thập Môi trường & Lịch sử")

        # THỰC THI PIPELINE TRÍCH XUẤT ĐẶC TRƯNG TƯƠNG ĐỒNG (FEATURE DERIVATION)
        if btn_fetch:
            with st.spinner("Đang kết nối API OpenMeteo & Quét CSDL Tìm kiếm chuyến bay tương đồng..."):
                # 1. Gọi API khí tượng Live theo vị trí sân bay cất cánh
                w_score, w_precip, w_wind = fetch_live_weather(f_origin, f_date)
                st.session_state['live_weather_score'] = w_score
                st.session_state['live_precip'] = w_precip
                st.session_state['live_wind'] = w_wind

                # 2. Quét CSDL Gold tìm kiếm chuyến tương đồng gần nhất của tàu bay (Tail Number) hoặc Chuyến bay
                match_history = df_raw[df_raw['Tail_Number'].astype(str).str.upper() == f_tail.strip().upper()]
                if match_history.empty:
                    match_history = df_raw[df_raw['Flight_No'].astype(str).str.upper() == f_flight_no.strip().upper()]

                if not match_history.empty:
                    # Trích xuất các biến Lag và áp lực vận hành thực tế từ file Gold dự phòng
                    st.session_state['derived_inc_delay'] = float(match_history['Incoming_Delay'].median())
                    st.session_state['derived_buffer'] = float(match_history['Turnaround_Buffer_Actual'].median())
                else:
                    # Nội suy mặc định dựa trên đặc thù sân bay nếu là tàu bay mới tinh
                    st.session_state['derived_inc_delay'] = float(
                        df_raw[df_raw['Airport'] == f_origin]['Incoming_Delay'].median())
                    st.session_state['derived_buffer'] = float(
                        df_raw[df_raw['Airport'] == f_origin]['Turnaround_Buffer_Actual'].median())

                st.success("🎉 Đã hoàn tất tính toán đặc trưng thành công!")

    with col_out:
        st.subheader("📤 Giám sát Trạng thái Môi trường Vận hành")

        # Đảm bảo hiển thị số liệu trực quan không bao giờ bị trống
        em1, em2, em3 = st.columns(3)
        em1.metric("Turnaround Buffer", f"{st.session_state['derived_buffer']:.1f} p",
                   delta="Thâm hụt" if st.session_state['derived_buffer'] < 0 else "An toàn", delta_color="inverse")
        em2.metric("Trễ chặng trước (Incoming)", f"{st.session_state['derived_inc_delay']:.1f} p")
        em3.metric("Rủi ro Khí tượng", f"{st.session_state['live_weather_score']:.2f}")

        st.markdown("---")

        if st.button("🚀 Thực thi Dự đoán", type="primary"):
            with st.spinner("Đang chạy mô hình dự toán Scikit-Learn..."):
                f_airline = "Vietnam Airlines" if f_flight_no.upper().startswith("VN") else "VietJet Air"

                # CHẠY MODEL THỰC TẾ TỪ FILE .PKL
                if model_loaded:
                    form_inputs = {
                        'Scheduled_Hour': f_hour,
                        'Turnaround_Buffer': st.session_state['derived_buffer'],
                        'Turnaround_Buffer_Model': st.session_state['derived_buffer'],
                        'Prev_Departure_Delay_Tail_1': st.session_state['derived_inc_delay'],
                        'Weather_Delay_Risk_Score': st.session_state['live_weather_score'],
                        'Visibility_Severity_Score': st.session_state['live_weather_score'] * 0.5,
                        'Is_Wide_Body': 1 if f_ac_type.upper() in ['A350', 'B787', 'A359', 'B789'] else 0
                    }

                    # Ánh xạ chuẩn hóa mảng vector 1D khớp hoàn hảo với model_training
                    input_row = {}
                    for col in model_features:
                        if col in form_inputs:
                            input_row[col] = form_inputs[col]
                        elif f"_{f_origin}" in col:
                            input_row[col] = 1
                        elif f"_{f_airline.split()[0]}" in col:
                            input_row[col] = 1
                        elif col.startswith("Airport_") or col.startswith("Origin_") or col.startswith(
                                "Airline_") or col.startswith("Aircraft_Type_"):
                            input_row[col] = 0
                        else:
                            # Điền trung vị lịch sử của file gold để bảo vệ hệ thống không bị NaN
                            val = df_raw[col].median() if col in df_raw.columns and pd.api.types.is_numeric_dtype(
                                df_raw[col]) else 0
                            input_row[col] = val if pd.notna(val) else 0

                    input_df = pd.DataFrame([input_row])[model_features]
                    st.session_state['feature_vector_df'] = input_df
                    st.session_state['prediction_minutes'] = int(max(0, model.predict(input_df)[0]))
                else:
                    # Thuật toán toán học dự phòng
                    st.session_state['prediction_minutes'] = int(max(0, 5 + (
                        abs(st.session_state['derived_buffer']) * 1.3 if st.session_state[
                                                                             'derived_buffer'] < 0 else 0)))

                # LUỒNG 2: GỌI HỆ CHUYÊN GIA LLM CHẨN ĐOÁN
                payload_to_llm = {
                    "Flight_No": f_flight_no, "Departure_Delay": st.session_state['prediction_minutes'],
                    "Turnaround_Buffer": st.session_state['derived_buffer'],
                    "Weather_Delay_Risk_Score": st.session_state['live_weather_score']
                }
                st.session_state['llm_diagnose'] = predict_delay_reason_local(payload_to_llm)

        # HIỂN THỊ KẾT QUẢ ĐẦU RA SAU KHI CLICK DỰ BÁO
        if st.session_state['prediction_minutes'] > 0 or st.session_state['llm_diagnose'] is not None:
            st.markdown(
                f"<h3 style='text-align: center; color: #d32f2f;'>⏱️ KẾT QUẢ DỰ BÁO: TRỄ {st.session_state['prediction_minutes']} PHÚT</h3>",
                unsafe_allow_html=True)

            if st.session_state['llm_diagnose']:
                d_code = st.session_state['llm_diagnose'].get('Delay_Code', 'CODE_99')
                d_reason = st.session_state['llm_diagnose'].get('Reason', 'Phân tích hoàn tất.')
                st.markdown(f"""
                <div class='llm-box'>
                    <h4 style='color: #ff9800; margin-top:0;'>🧠 Lý do trễ</h4>
                    <p><b>Mã Nguyên Nhân IATA:</b> <span style='color:#d32f2f; font-weight:bold;'>{d_code}</span></p>
                    <p><b>Chẩn đoán chi tiết:</b> {d_reason}</p>
                </div>
                """, unsafe_allow_html=True)

            # MLOPS: CHỈ HIỂN THỊ CÁC FEATURE THỰC TẾ ĐƯỢC TÍNH TOÁN VÀ NẠP VÀO MODEL
            if model_loaded and st.session_state['feature_vector_df'] is not None:
                with st.expander("🔍 MLOps: Quản lý Đặc trưng Được Tính toán"):
                    st.dataframe(st.session_state['feature_vector_df'], width="stretch")