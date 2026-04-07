"""Nota numbering and lookup utilities — derived from NOTA_GROUPS config."""

from config.nota import NOTA_GROUPS


def numbered_groups(has_data_fn=None):
    """Yield (group, [(nota_num, entry), ...]) with auto-incrementing numbers.

    Empty entries (where *has_data_fn* returns False) are skipped and
    do not consume a nota number.  Groups with no surviving entries are
    omitted entirely.
    """
    result = []
    nota = 1
    for group in NOTA_GROUPS:
        numbered_entries = []
        for entry in group.entries:
            if has_data_fn is not None and not has_data_fn(entry):
                continue
            numbered_entries.append((nota, entry))
            nota += 1
        if numbered_entries:
            result.append((group, numbered_entries))
    return result


def nota_title(num: int, label: str) -> str:
    return f"Nota {num:02d}. {label}"


def build_partida_nota_map(has_data_fn=None):
    """Return {partida_label: nota_str} for all entries with partida_labels defined.

    When multiple nota entries share the same partida_label (e.g. RESULTADO FINANCIERO
    covered by both Ingresos Financieros and Gastos Financieros), the numbers are
    combined as "06 & 07".
    """
    result = {}  # partida_label -> list of nota nums
    for group, numbered_entries in numbered_groups(has_data_fn):
        for num, entry in numbered_entries:
            for label in entry.partida_labels:
                result.setdefault(label, []).append(num)
    return {k: " & ".join(f"{n:02d}" for n in v) for k, v in result.items()}
