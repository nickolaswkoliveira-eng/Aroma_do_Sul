import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from utils.session_state import RESET_SESSION_ON_RERUN


class AppStateTests(unittest.TestCase):
    def test_order_filter_survives_card_navigation(self):
        app_file = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_file)).run()
        app.session_state["active_page"] = "Pedidos"
        app.run()
        app.selectbox(key="orders.category").select("Todas").run()
        app.text_input(key="orders.customer_name").set_value("Ana").run()
        app.session_state["active_page"] = "Início"
        app.run()
        app.session_state["active_page"] = "Pedidos"
        app.run()
        self.assertEqual(app.selectbox(key="orders.category").value, "Todas")
        self.assertEqual(app.text_input(key="orders.customer_name").value, "Ana")
        self.assertEqual(len(app.exception), 0)

    def test_last_report_survives_navigation(self):
        app_file = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_file)).run()
        app.session_state["active_page"] = "Relatórios"
        app.run()
        app.button(key="report_Produtos").click().run()
        app.session_state["active_page"] = "Início"
        app.run()
        app.session_state["active_page"] = "Relatórios"
        app.run()
        self.assertEqual(app.session_state["report_section"], "Produtos")
        self.assertEqual(len(app.exception), 0)

    def test_home_displays_fast_operational_summary(self):
        app_file = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_file)).run()
        metric_labels = [metric.label for metric in app.metric]
        self.assertEqual(
            metric_labels,
            ["Vendas hoje", "Pedidos em andamento", "Caixa", "Estoque crítico"],
        )
        visible_text = "\n".join(element.value for element in app.markdown)
        section_titles = [element.value for element in app.subheader]
        self.assertIn("Central de operação", visible_text)
        self.assertIn("Resumo rápido", section_titles)
        self.assertEqual(len(app.exception), 0)

    def test_mobile_navigation_opens_authorized_module(self):
        app_file = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_file)).run()
        app.selectbox(key="mobile_nav_select").select("Pedidos").run()
        self.assertEqual(app.session_state["active_page"], "Pedidos")
        self.assertEqual(len(app.exception), 0)

    def test_logout_reset_clears_session_values_on_next_run(self):
        app_file = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_file)).run()
        app.session_state["private_widget"] = "old value"
        app.session_state[RESET_SESSION_ON_RERUN] = True
        app.run()
        self.assertNotIn("private_widget", app.session_state)
        self.assertEqual(len(app.exception), 0)

    def test_management_dashboard_renders_compact_sections(self):
        app_file = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_file)).run()
        app.session_state["active_page"] = "Visão geral"
        app.run()
        section_titles = "\n".join(element.value for element in app.subheader)
        self.assertIn("Resumo do dia", section_titles)
        self.assertIn("CMV", section_titles)
        self.assertIn("Atenção hoje", section_titles)
        self.assertNotIn("Resumo de hoje", section_titles)
        self.assertEqual(len(app.exception), 0)

    def test_kitchen_tv_mode_uses_expanded_layout(self):
        app_file = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_file)).run()
        app.session_state["active_page"] = "Cozinha"
        app.run()
        app.toggle(key="kitchen.tv_mode").set_value(True).run()
        self.assertTrue(app.session_state["kitchen.tv_mode"])
        self.assertTrue(any(
            "st-key-top_navigation_mobile" in element.value for element in app.markdown
        ))
        self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()
