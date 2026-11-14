import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import "./index.css"
import "katex/dist/katex.min.css"
import App from "./App"
import { AuthProvider } from "./lib/auth"
import { I18nProvider } from "./lib/i18n"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <I18nProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </I18nProvider>
    </BrowserRouter>
  </StrictMode>,
)
