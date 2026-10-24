const STANDARDS: Array<{ topic: string; sni: string; astm: string }> = [
  { topic: 'Standard Penetration Test (SPT)', sni: 'SNI 4153:2008', astm: 'ASTM D1586' },
  { topic: 'Cone penetration test (sondir / CPTu)', sni: 'SNI 2827:2008', astm: 'ASTM D3441 (mechanical), ASTM D5778 (electronic)' },
  { topic: 'Soil classification (USCS)', sni: 'SNI 6371:2015', astm: 'ASTM D2487' },
  { topic: 'Logging of core drilling', sni: 'SNI 2436:2008', astm: '-' },
]

export default function AboutSoilBoring() {
  return (
    <div className="card" style={{ lineHeight: 1.6 }}>
      <h2 style={{ marginTop: 0 }}>Why Soil Boring Matters</h2>
      <p>
        Soil boring and in-situ testing are the first look at what lies under a site. The results decide
        whether the ground can carry the planned structure, which foundation to use, and which risks have to be
        priced in before construction starts.
      </p>

      <h3>Key Objectives</h3>
      <ol>
        <li>
          <strong>Determine soil characteristics:</strong> soil type (clay, silt, sand, gravel), consistency or
          density, and strength parameters for bearing capacity.
        </li>
        <li>
          <strong>Assess stability and bearing capacity:</strong> check that the ground can safely carry the
          structure without excessive settlement, lateral movement or failure.
        </li>
        <li>
          <strong>Select the foundation type:</strong> shallow footings, bored or driven piles, including their
          depth and size.
        </li>
        <li>
          <strong>Identify geotechnical risks:</strong> soft or expansive layers, high groundwater, contamination
          or difficult rock horizons.
        </li>
        <li>
          <strong>Support planning and costing:</strong> realistic methods, schedules and budgets before
          mobilisation.
        </li>
      </ol>

      <h3>Field Methods in This App</h3>
      <ul>
        <li><strong>Wash boring / rotary wash + SPT:</strong> open-hole drilling with SPT at set intervals; the log keeps the average N60.</li>
        <li><strong>Coring + SPT:</strong> rotary core drilling for stiff soil and rock, with SPT in the soil sections.</li>
        <li><strong>Hollow stem auger</strong> and <strong>hand auger:</strong> shallow holes and sampling without drilling fluid.</li>
        <li><strong>CPT / CPTu (sondir):</strong> cone penetration soundings; record the final penetration depth as the final depth.</li>
      </ul>

      <h3>Reference Standards</h3>
      <p style={{ marginTop: 0 }}>Field work and classification are normally carried out to the Indonesian national standard (SNI) or its ASTM counterpart:</p>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: '480px' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: '.35rem', borderBottom: '1px solid var(--border)' }}>Topic</th>
              <th style={{ textAlign: 'left', padding: '.35rem', borderBottom: '1px solid var(--border)' }}>SNI</th>
              <th style={{ textAlign: 'left', padding: '.35rem', borderBottom: '1px solid var(--border)' }}>ASTM</th>
            </tr>
          </thead>
          <tbody>
            {STANDARDS.map(s => (
              <tr key={s.topic}>
                <td style={{ padding: '.35rem', borderBottom: '1px dashed var(--border)' }}>{s.topic}</td>
                <td style={{ padding: '.35rem', borderBottom: '1px dashed var(--border)' }}>{s.sni}</td>
                <td style={{ padding: '.35rem', borderBottom: '1px dashed var(--border)' }}>{s.astm}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>How This App Helps</h3>
      <ul>
        <li>One place for every borehole log: location, drilling method, depths, groundwater, USCS class and SPT N60.</li>
        <li>Dashboards and weekly/monthly summaries, with optional AI-written briefings for project stakeholders.</li>
        <li>Geo AI answers questions from the logged data and shows the rows it used as evidence.</li>
        <li>
          Exports: CSV for spreadsheets, and <strong>AGS4</strong> (one project per file) for geotechnical software
          such as gINT, HoleBASE or OpenGround.
        </li>
      </ul>
    </div>
  )
}
