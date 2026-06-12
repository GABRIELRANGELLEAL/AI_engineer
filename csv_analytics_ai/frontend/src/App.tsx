import { useState } from 'react';
import DataSourceSelector from './components/DataSourceSelector';
import WorkspacePage from './components/WorkspacePage';

type Screen = 'source' | 'workspace';

function App() {
  const [screen, setScreen] = useState<Screen>('source');
  const [dataSourceType, setDataSourceType] = useState<'csv' | 'database' | null>(null);

  const handleSelectSource = (type: 'csv' | 'database') => {
    setDataSourceType(type);
    setScreen('workspace');
  };

  const handleBack = () => {
    setScreen('source');
    setDataSourceType(null);
  };

  return (
    <div className="min-h-screen">
      {screen === 'source' ? (
        <DataSourceSelector onSelectSource={handleSelectSource} />
      ) : (
        <WorkspacePage dataSourceType={dataSourceType!} onBack={handleBack} />
      )}
    </div>
  );
}

export default App;
