import Plot from 'react-plotly.js';
import ReactMarkdown from 'react-markdown';

export interface TextBlock {
  type: 'text';
  content: string;
}

export interface TableBlock {
  type: 'table';
  title: string;
  columns: string[];
  rows: (string | number)[][];
}

export interface PlotBlock {
  type: 'plot';
  title: string;
  library: 'plotly';
  spec: {
    data: any[];
    layout: any;
  };
}

export type Block = TextBlock | TableBlock | PlotBlock;

interface Props {
  block: Block;
}

export default function UIBlock({ block }: Props) {
  if (block.type === 'text') {
    return (
      <div className="prose prose-sm max-w-none prose-invert prose-p:text-slate-300 prose-headings:text-slate-100 prose-strong:text-slate-200 prose-li:text-slate-300">
        <ReactMarkdown>{block.content}</ReactMarkdown>
      </div>
    );
  }

  if (block.type === 'table') {
    return (
      <div className="mt-4">
        <h4 className="text-sm font-semibold text-slate-200 mb-2">
          {block.title}
        </h4>
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse border border-slate-600 rounded">
            <thead>
              <tr className="bg-slate-800">
                {block.columns.map((col, i) => (
                  <th
                    key={i}
                    className="border border-slate-600 px-3 py-2 text-left text-slate-300 font-medium"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, i) => (
                <tr key={i} className="hover:bg-slate-800/50 transition">
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      className="border border-slate-600 px-3 py-2 text-slate-300"
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (block.type === 'plot' && block.library === 'plotly') {
    return (
      <div className="mt-4 w-full">
        <h4 className="text-sm font-semibold text-slate-200 mb-2">
          {block.title}
        </h4>
        <div className="bg-slate-800 rounded-lg p-4 w-full">
          <Plot
            data={block.spec.data}
            layout={{
              ...block.spec.layout,
              autosize: true,
              paper_bgcolor: 'rgba(30, 41, 59, 1)',
              plot_bgcolor: 'rgba(51, 65, 85, 1)',
              font: { color: '#cbd5e1', size: 12 },
              margin: { l: 50, r: 30, t: 50, b: 50 },
            }}
            config={{
              responsive: true,
              displayModeBar: true,
              displaylogo: false,
              modeBarButtonsToRemove: ['lasso2d', 'select2d'],
            }}
            useResizeHandler
            style={{ width: '100%', height: '500px' }}
            className="w-full"
          />
        </div>
      </div>
    );
  }

  return null;
}
