import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function scrapeWebsite({ url, prompt, useAi, provider }) {
  const response = await axios.post(`${API_BASE_URL}/scrape`, {
    url,
    prompt,
    use_ai: useAi,
    provider: useAi ? provider : null,
  });

  return response.data;
}

export async function generateScript({ url, prompt, language, provider, groundOnHtml }) {
  const response = await axios.post(`${API_BASE_URL}/generate-script`, {
    url,
    prompt,
    language,
    provider,
    ground_on_html: groundOnHtml,
  });

  return response.data;
}

export function downloadText(text, filename) {
  const blob = new Blob([text], { type: "text/plain" });
  const downloadUrl = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(downloadUrl);
}

export async function exportData(data, format) {
  const response = await axios.post(
    `${API_BASE_URL}/export`,
    {
      data,
      format,
    },
    {
      responseType: "blob",
    }
  );

  const blob = new Blob([response.data]);
  const downloadUrl = window.URL.createObjectURL(blob);

  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = format === "csv" ? "scraped_data.csv" : "scraped_data.json";
  document.body.appendChild(link);
  link.click();
  link.remove();

  window.URL.revokeObjectURL(downloadUrl);
}
