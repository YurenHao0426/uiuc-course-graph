import Graph from "./components/Graph";
import { useCourseData } from "./hooks/useCourseData";

export default function App() {
  const catalog = useCourseData("/data/catalog_2025_fall.json");
  return (
    <>
      <h1 style={{ textAlign: "center" }}>UIUC Course Prerequisite Graph</h1>
      <Graph catalog={catalog} />
    </>
  );
}
