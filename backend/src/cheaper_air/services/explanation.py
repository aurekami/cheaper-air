from cheaper_air.domain.models import SearchResult


def explain(result: SearchResult):
    """Render factual amounts server-side; no model-authored financial claims."""
    if result.data_mode == 'REAL':
        summary = f"Gauta {len(result.observations)} API kainų stebėjimų. "
        if result.observations:
            best = min(result.observations, key=lambda o: o.price.amount)
            summary += f"Mažiausia stebėta kaina {best.price.amount} EUR. "
        summary += "Bagažo ir tarifo sąlygos bei pardavimo rinka nepatvirtintos, todėl sutaupymas neskaičiuojamas."
        return {"summary": summary, "evidence_refs": [o.id for o in result.observations]}
    parts, references = ["MOCK demonstraciniai rezultatai."], []
    for group in result.comparison_groups:
        best = group.offers[0]
        references.append(best.offer_id)
        line = f"Grupėje {group.id} pigiausias lygiavertis pasiūlymas {best.offer_id}: {best.total_eur} EUR."
        if best.savings_eur is not None:
            line += f" Skirtumas nuo bazinės rinkos: {best.savings_eur} EUR ({best.savings_percent} %)."
        else:
            line += " Bazinės rinkos pasiūlymo nėra; sutaupymas nenustatytas."
        parts.append(line)
    if not result.comparison_groups:
        parts.append("Palyginamų pasiūlymų nerasta.")
    parts.append("Galimybė įsigyti kitoje pardavimo rinkoje nepatvirtinta.")
    return {"summary": " ".join(parts), "evidence_refs": references}
