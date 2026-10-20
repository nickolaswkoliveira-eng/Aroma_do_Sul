from io import BytesIO
import qrcode
import streamlit as st


def render_qr() -> None:
    with st.expander("Compartilhar pedidos por QR Code"):
        st.caption("Informe o endereço de rede do Streamlit acessível pelo celular do cliente.")
        address = st.text_input("URL pública da tela de pedidos", placeholder="http://192.168.0.10:8501")
        if address:
            image = qrcode.make(address.rstrip("/") + "/?pagina=Pedidos")
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            st.image(buffer.getvalue(), width=180, caption="Aponte a câmera para abrir os pedidos")
            st.code(address.rstrip("/") + "/?pagina=Pedidos")
