export default function FieldTable({ fields }) {
  if (!fields || fields.length === 0) {
    return <p className="no-data">No SAP fields detected for this rule.</p>
  }

  return (
    <div className="field-table-wrapper">
      <table className="field-table">
        <thead>
          <tr>
            <th>Field</th>
            <th>Business Name</th>
            <th>Description</th>
            <th>Table</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((f, i) => (
            <tr key={i}>
              <td><span className="mono-pill">{f.field}</span></td>
              <td className="field-business-name">{f.business_name}</td>
              <td className="desc-cell">{f.description || '—'}</td>
              <td><span className="mono-pill">{f.table || '—'}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
