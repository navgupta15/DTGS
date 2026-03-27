from pathlib import Path
from toolmaker.analyzer.java_analyzer import _parser
import json

src = Path("testrepo/src/MyCtrl.java").read_bytes()
tree = _parser.parse(src)

def print_tree(node, indent=0):
    print(" " * indent + node.type + " " + (node.text.decode('utf-8') if not node.children else ""))
    for child in node.children:
        print_tree(child, indent + 2)

print_tree(tree.root_node)
