import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import AdminPage from './components/AdminPage.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import './styles/main.css'

function Root() {
  const isAdmin = window.location.pathname.startsWith('/admin')
  return isAdmin ? <AdminPage /> : <App />
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <Root />
    </ErrorBoundary>
  </React.StrictMode>
)

