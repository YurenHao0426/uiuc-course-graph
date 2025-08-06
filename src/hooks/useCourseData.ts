import { useEffect, useState } from "react";

export function useCourseData(file = "/data/catalog_2025_fall.json") {
  const [catalog, setCatalog] = useState<Record<string, string[]>>({});

  useEffect(() => {
    fetch(file)
      .then(r => r.json())
      .then(setCatalog)
      .catch(console.error);
  }, [file]);

  return catalog;
}
