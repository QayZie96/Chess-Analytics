import ast, nbformat
from nbformat.v4 import new_notebook,new_markdown_cell,new_code_cell
cells=[new_markdown_cell('# Chess Analytics MVP - Python EDA Stage 1\nEarly-August sample; observational only.'),new_markdown_cell('## Safe data access\nThe validated module uses DuckDB aggregates and excludes player identifiers.'),new_code_cell("from pathlib import Path\nimport sys\nroot=Path.cwd().resolve()\nif not (root/'src').exists(): root=root.parent\nsys.path.insert(0,str(root))\nfrom src.mvp_eda import run"),new_markdown_cell('## Data quality, feature engineering, and checks'),new_code_cell("metrics=run()\nlabels=['games','duplicate_ids','invalid_ratings','invalid_results','missing_openings','rating_change_pairs','upset_eligible','upsets','comparable_opponents']\ndict(zip(labels,metrics))"),new_markdown_cell('## Limitations\nNo causal claims, charts, or Power BI work are included in Stage 1.')]
cells[2].source = cells[2].source.replace(
    'from src.mvp_eda import run',
    'from src.mvp_eda import rating_distribution_chart, upset_rate_by_gap_chart, result_distribution_by_speed_chart, run',
)
cells[-1:-1] = [
    new_markdown_cell(
        '## Chart 1 - Player rating distribution by game color\n'
        'How are player ratings distributed across White and Black game-side appearances '
        'in our sample?'
    ),
    new_code_cell(
        'from IPython.display import display\n'
        'rating_figure, rating_bins = rating_distribution_chart()\n'
        'display(rating_figure)'
    ),
    new_markdown_cell(
        'The peak band is 1700-1799 for both colors: 45,630 White appearances and '
        '45,463 Black appearances. These are game-side appearances, not unique players. '
        'The early-August sample does not represent the whole month.'
    ),
]
cells[-1:-1] = [
    new_markdown_cell(
        '## Chart 2 - Observed upset rate by rating-gap band\n'
        'Among eligible games, how does the observed lower-rated-player win rate vary '
        'with the pre-game rating gap?'
    ),
    new_code_cell(
        'upset_figure, upset_bands = upset_rate_by_gap_chart()\n'
        'display(upset_figure)\n'
        "upset_bands.assign(upset_rate_pct=upset_bands['upset_rate_pct'].round(2))"
    ),
    new_markdown_cell(
        'The calculated table and chart describe eligible games in this early-August sample. '
        'They are observed rates, not universal upset probabilities; draws remain in each '
        'band denominator.'
    ),
]
cells[-1:-1] = [
    new_markdown_cell(
        '## Chart 3 - Game-result distribution by speed category\n'
        'How do observed White wins, Black wins, and draws differ across the recorded '
        'game-speed categories?'
    ),
    new_code_cell(
        'speed_figure, speed_results = result_distribution_by_speed_chart()\n'
        'display(speed_figure)\n'
        "speed_results.assign(white_win_pct=speed_results['white_win_pct'].round(2), "
        "black_win_pct=speed_results['black_win_pct'].round(2), "
        "draw_pct=speed_results['draw_pct'].round(2))"
    ),
    new_markdown_cell(
        'The chart retains every recorded speed category, including the small correspondence '
        'sample. These descriptive differences are associations in the early-August sample, '
        'not causal effects of time control.'
    ),
]
n=new_notebook(cells=cells)
for i,c in enumerate(n.cells):
 if c.cell_type=='code': ast.parse(c.source,filename=f'cell_{i}')
nbformat.write(n,'notebooks/01_mvp_eda.ipynb')
print('builder ok')
