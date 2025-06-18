# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License - see LICENSE file in this repo.

import re
import networkx as nx
import sys
from networkx.drawing.nx_pydot import write_dot
from os.path import splitext

def process_stack_file(input_path):
    # Compile regex patterns for symbolized frames and slot counts
    rgx_already_symbolized_frame = re.compile(
        r"((?P<framenum>\d+)\s+)*(?P<module>\w+)(\.(dll|exe))*!(?P<symbolizedfunc>.+?)\s*\+\s*(0[xX])*(?P<offset>[0-9a-fA-F]+)\s*"
    )
    rgx_slot_count = re.compile(
        r"Slot_(?P<slotidx>\d+)\s+\[count\:(?P<slotcount>\d+)\]\:"
    )

    captured_input = []
    current_stack = []

    # Read the input file and split into stacks based on slot count lines
    with open(input_path, "r", encoding="utf-8") as sr:
        for line in sr:
            line = line.replace("::", "--").strip()
            mtch = rgx_slot_count.match(line)
            if mtch:
                captured_input.extend(current_stack)
                current_stack = []

            current_stack.append(line)

        # Handle last stack
        captured_input.extend(current_stack)

    # Initialize directed graph
    G = nx.DiGraph()
    prev_node = None
    slotidx = -1
    slotcount = 0

    # Helper to add or update a node with slot count
    def get_or_create_node(node_id, slotcount, slotidx):
        if node_id not in G:
            G.add_node(node_id, SlotCount=slotcount)
        else:
            # Node already exists, update weight
            G.nodes[node_id]["SlotCount"] += slotcount

        return G.nodes[node_id]

    idx = 0
    # Iterate through captured input lines to build the graph
    while idx < len(captured_input):
        line = captured_input[idx].strip()
        idx += 1
        if not line:
            prev_node = None
            continue

        mtch = rgx_slot_count.match(line)
        if mtch:
            slotidx = int(mtch.group("slotidx"))
            slotcount = int(mtch.group("slotcount"))

        mtch = rgx_already_symbolized_frame.match(line)
        if mtch:
            node_id = line
            node = get_or_create_node(node_id, slotcount, slotidx)

            if prev_node:
                edge_key = (node_id, prev_node)
                if not G.has_edge(node_id, prev_node):
                    G.add_edge(
                        node_id,
                        prev_node,
                        SlotCount=slotcount,
                    )
                else:
                    G.edges[edge_key]["SlotCount"] += slotcount
            prev_node = node_id

    # Coalesce nodes: merge nodes with a single in-edge and their source has a single out-edge
    while True:
        nodes_to_remove = []
        for n in list(G.nodes):
            in_edges = list(G.in_edges(n))
            if len(in_edges) == 1:
                from_node = in_edges[0][0]
                out_edges = list(G.out_edges(from_node))
                if len(out_edges) == 1:
                    # Merge from_node into n
                    G.nodes[n]["label"] = (
                        G.nodes[n].get("label", n)
                        + "\n"
                        + G.nodes[from_node].get("label", from_node)
                    )
                    # Redirect in-edges of from_node to n
                    for e in list(G.in_edges(from_node)):
                        G.add_edge(e[0], n, **G.edges[e])
                        G.remove_edge(*e)
                    G.remove_node(from_node)
                    nodes_to_remove.append(from_node)
        if not nodes_to_remove:
            break

    # Calculate total slot counts for edges
    # total_slot_count_from_nodes = sum(n["SlotCount"] for n in G.nodes().values())
    total_slot_count_from_edges = sum(e["SlotCount"] for e in G.edges().values())

    # Add attributes to nodes and edges for DOT output
    for n in G.nodes:
        # include the slot count ("samples") in the node labels
        G.nodes[n]["label"] = (
            f"{G.nodes[n].get('label', n)}\t({G.nodes[n].get('SlotCount', n)} samples)".replace(
                "--", "::"
            )
        )

    for e in G.edges:
        G.edges[e]["label"] = (
            "<<I>" + f"{G.edges[e].get('SlotCount', 0)} switches" + "</I>>"
        )
        pen_width = max(
            G.edges[e].get("SlotCount", 0) / total_slot_count_from_edges * 256.0, 1
        )
        G.edges[e]["penwidth"] = f"{pen_width}"

    # Set DOT graph, node, and edge attributes
    G.graph["graph"] = {"rankdir": "BT" }# , "size": "11.0,17.0", "ratio": 0.647}
    G.graph["node"] = {
        "shape": "rect",
        "style": "rounded",
        "fontname": "Segoe UI",
        "fontsize": 40.0,
    }
    G.graph["edge"] = {
        "color": "grey",
        "fillcolor": "grey",
        "fontname": "Segoe UI",
        "fontsize": 32.0,
    }

    return G

G = process_stack_file(sys.argv[1])
out_filename_without_ext = splitext(sys.argv[1])[0]
write_dot(G, out_filename_without_ext + ".dot")
nx.nx_agraph.to_agraph(G).draw(path=out_filename_without_ext + ".svg", prog='dot',format='svg')

# print all simple paths in the graph
paths = []
for source in G.nodes:
    for target in G.nodes:
        if source != target:
            for path in nx.all_simple_paths(G, source=source, target=target):
                # get the total weight of the path and print it
                # print(" -> ".join(path) + f" SlotCount: {nx.path_weight(G, path, weight='SlotCount')}")
                # append the path, and it's length to a list
                paths.append((path, nx.path_weight(G, path, weight='SlotCount')))

# sort the paths by length, descending, and print the top 2
paths.sort(key=lambda x: x[1], reverse=True)
print("\nTop 2 longest paths:")
for path, length in paths[:2]:
    print(" -> ".join(path) + f" Length: {length}")
