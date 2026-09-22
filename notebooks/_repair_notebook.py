import ast
import nbformat

path = "notebooks/01_mvp_eda.ipynb"
notebook = nbformat.read(path, as_version=4)
targets = [
    ('FROM games\n""').replace('""', '""'),
]
for cell in notebook.cells:
    if cell.cell_type != "code":
        continue
    source = cell.source
    source = source.replace('"".df()', '""".df()')
    source = source.replace('""")\ncon.execute', '""")\ncon.execute')
    source = source.replace('"".fetchone()', '""".fetchone()')
    cell.source = source
for index, cell in enumerate(notebook.cells):
    if cell.cell_type == "code":
        ast.parse(cell.source, filename=f"cell_{index}")
nbformat.write(notebook, path)
print("all code cells parse")
