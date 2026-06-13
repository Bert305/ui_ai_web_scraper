import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const ACCESS_KEY_STORAGE = "app_access_key";

export function getAccessKey() {
  return localStorage.getItem(ACCESS_KEY_STORAGE) || "";
}

export function setAccessKey(key) {
  if (key) localStorage.setItem(ACCESS_KEY_STORAGE, key);
  else localStorage.removeItem(ACCESS_KEY_STORAGE);
}

export function clearAccessKey() {
  localStorage.removeItem(ACCESS_KEY_STORAGE);
}

// Attach the shared access key to every request (if one is stored).
axios.interceptors.request.use((config) => {
  const key = getAccessKey();
  if (key && !config.headers["X-App-Key"]) {
    config.headers["X-App-Key"] = key;
  }
  return config;
});

// If the server rejects the key, drop it and let the app re-lock.
axios.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      clearAccessKey();
      window.dispatchEvent(new Event("app-unauthorized"));
    }
    return Promise.reject(error);
  }
);

// Validate the stored key (or confirm auth is disabled). Throws on 401.
export async function checkAccess() {
  await axios.get(`${API_BASE_URL}/auth/check`);
  return true;
}

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

export async function generateSql({
  schemaSql,
  prompt,
  dialect,
  includeQueries,
  includeErd,
  provider,
}) {
  const response = await axios.post(`${API_BASE_URL}/generate-sql`, {
    schema_sql: schemaSql,
    prompt,
    dialect,
    include_queries: includeQueries,
    include_erd: includeErd,
    provider,
  });

  return response.data;
}

export async function analyzeData({ file, prompt, provider, includeSql }) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("prompt", prompt);
  formData.append("provider", provider || "auto");
  formData.append("include_sql", includeSql ? "true" : "false");

  const response = await axios.post(`${API_BASE_URL}/analyze-data`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
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
