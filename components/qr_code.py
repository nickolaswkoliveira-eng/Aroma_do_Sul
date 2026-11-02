from io import BytesIO
import qrcode
import streamlit as st


def render_qr() -> None:
    with st.expander("QR Code de atendimento por mesa"):
        st.caption(
            "Informe o endereço de rede do Streamlit acessível no celular do atendente. "
            "Cada QR abre a mesa correspondente no modo rápido (pedidos, comandas e status)."
        )
        address = st.text_input("URL pública da aplicação", placeholder="http://192.168.0.10:8501")
        if address:
            base = address.rstrip("/")
            columns = st.columns(5)
            for table_number in range(1, 6):
                url = f"{base}/?pagina=Pedidos&acesso=atendimento&mesa={table_number:02d}"
                image = qrcode.make(url)
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                with columns[table_number - 1]:
                    st.image(buffer.getvalue(), width=150, caption=f"Mesa {table_number:02d}")
            st.code(f"{base}/?pagina=Pedidos&acesso=atendimento&mesa=01")
