import CytoscapeComponent from "react-cytoscapejs";
import cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";
import { useMemo } from "react";

cytoscape.use(dagre);

type Catalog = Record<string, string[]>;

export default function Graph({ catalog }: { catalog: Catalog }) {
  const elements = useMemo(() => {
    const els: any[] = [];
    Object.keys(catalog).forEach(id => {
      els.push({ data: { id } });
      catalog[id].forEach(p =>
        els.push({
          data: { id: `${p}->${id}`, source: p, target: id }
        })
      );
    });
    return els;
  }, [catalog]);

  return (
    <CytoscapeComponent
      elements={elements}
      stylesheet={[
        {
          selector: "node",
          style: {
            "background-color": "#3182bd",
            label: "data(id)",
            color: "#fff"
          }
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "target-arrow-shape": "triangle",
            "curve-style": "bezier"
          }
        }
      ]}
      layout={{ name: "dagre", rankDir: "TB", nodeSep: 30, rankSep: 50 }}
      style={{ width: "100%", height: "90vh" }}
    />
  );
}
