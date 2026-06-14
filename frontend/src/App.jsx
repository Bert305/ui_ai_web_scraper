import { useState } from "react";
import Scraper from "./Scraper";
import ScriptGenerator from "./ScriptGenerator";
import SqlGenerator from "./SqlGenerator";
import DataAnalyzer from "./DataAnalyzer";

const TABS = [
  {
    id: "scrape",
    label: "Scrape Data",
    eyebrow: "AI Scraping Tool",
    title: "Prompt-based Web Scraper",
    subtitle:
      "Enter a URL, describe the data you want, preview the extracted data, then export it as CSV or JSON.",
  },
  {
    id: "generate",
    label: "Generate Script",
    eyebrow: "For Developers",
    title: "Custom Web Scraping Script Generator",
    subtitle:
      "Describe what to extract and pick a stack — get a runnable script with selectors grounded in the real page HTML.",
  },
  {
    id: "sql",
    label: "SQL & ERD",
    eyebrow: "Database Tools",
    title: "SQL Queries and ERDs from a Schema",
    subtitle:
      "Paste your PostgreSQL DDL, describe what you want — get queries and a visual ERD grounded in your schema.",
  },
  {
    id: "analyze",
    label: "Analyze Data",
    eyebrow: "Spreadsheet Analytics",
    title: "KPIs, Metrics & Charts from a Spreadsheet",
    subtitle:
      "Upload a CSV, Excel, or JSON file and describe the stats you want — get accurate KPIs, rendered charts, and the SQL query that finds the same numbers.",
  },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("scrape");
  const tab = TABS.find((t) => t.id === activeTab);

  function renderTab() {
    if (activeTab === "scrape") return <Scraper />;
    if (activeTab === "generate") return <ScriptGenerator />;
    if (activeTab === "sql") return <SqlGenerator />;
    return <DataAnalyzer />;
  }

  return (
    <main className="page">
      <section className="hero">
        <div>
          <p className="eyebrow">{tab.eyebrow}</p>
          <h1>{tab.title}</h1>
          <p className="subtitle">{tab.subtitle}</p>
        </div>
      </section>

      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={activeTab === t.id}
            className={`tab ${activeTab === t.id ? "tabActive" : ""}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {renderTab()}
    </main>
  );
}
