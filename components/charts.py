from datetime import date, timedelta

from plotly.graph_objects import Figure

from utils.palette import BACKGROUND, BEIGE_DARK, CHART_COLORS

WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def format_sales_series(orders: list, period: str, start: date | None = None,
                        end: date | None = None) -> tuple[list[str], list[float]]:
    if not orders:
        return [], []
    totals: dict[str, float] = {}
    for order in orders:
        created = order.created_at
        if period == "Dia":
            label = created.strftime("%H:00")
        elif period == "Semana":
            label = WEEKDAYS[created.weekday()]
        elif period == "Ano":
            label = f"{MONTHS[created.month - 1]}/{created.year}"
        elif period == "Personalizado":
            label = created.strftime("%d/%m/%Y")
        else:
            label = created.strftime("%d/%m")
        totals[label] = totals.get(label, 0.0) + order.total

    if start is not None and end is not None and period == "Dia":
        labels = [f"{hour:02d}:00" for hour in range(24)]
    elif start is not None and end is not None and period == "Semana":
        labels = [WEEKDAYS[index] for index in range(start.weekday(), end.weekday() + 1)]
    elif start is not None and end is not None and period == "Ano":
        labels = [f"{MONTHS[month - 1]}/{start.year}" for month in range(1, end.month + 1)]
    elif start is not None and end is not None and period in ("Mês", "Personalizado"):
        date_format = "%d/%m/%Y" if period == "Personalizado" else "%d/%m"
        labels = [
            (start + timedelta(days=offset)).strftime(date_format)
            for offset in range((end - start).days + 1)
        ]
    elif period == "Dia":
        labels = sorted(totals, key=lambda value: int(value[:2]))
    elif period == "Semana":
        labels = WEEKDAYS
    elif period == "Ano":
        labels = sorted(totals, key=lambda label: (int(label.split("/")[1]), MONTHS.index(label.split("/")[0])))
    else:
        date_format = "%d/%m/%Y" if period == "Personalizado" else "%d/%m"
        date_by_label = {order.created_at.strftime(date_format): order.created_at.date() for order in orders}
        labels = sorted(totals, key=lambda label: date_by_label[label])
    return labels, [totals.get(label, 0.0) for label in labels]


def apply_chart_theme(figure: Figure, single_point: bool = False) -> Figure:
    figure.update_layout(
        template="plotly_white",
        paper_bgcolor=BACKGROUND,
        plot_bgcolor=BACKGROUND,
        font={"color": "#30251D", "family": "Inter, system-ui, sans-serif"},
        colorway=CHART_COLORS,
        margin={"l": 12, "r": 12, "t": 28, "b": 12},
        xaxis={"gridcolor": "rgba(74,53,39,0.12)", "linecolor": BEIGE_DARK,
               "tickfont": {"color": "#75685B"}},
        yaxis={"gridcolor": "rgba(74,53,39,0.12)", "linecolor": BEIGE_DARK,
               "tickfont": {"color": "#75685B"}},
    )
    if single_point:
        figure.update_traces(mode="lines+markers+text", marker={"size": 16}, textposition="top center",
                             selector={"type": "scatter"})
        figure.update_layout(yaxis={"visible": False, "showgrid": False, "zeroline": False},
                             xaxis={"type": "category", "showgrid": False, "showline": False})
    else:
        figure.update_traces(marker={"size": 8}, selector={"type": "scatter"})
    return figure
