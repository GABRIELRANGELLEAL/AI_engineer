import { useState } from 'react'
import SetupPage from './pages/SetupPage'
import MainPage from './pages/MainPage'

export default function App() {
  const [apiConfig, setApiConfig] = useState(null)

  if (!apiConfig) {
    return <SetupPage onComplete={setApiConfig} />
  }

  return <MainPage apiConfig={apiConfig} onBack={() => setApiConfig(null)} />
}
