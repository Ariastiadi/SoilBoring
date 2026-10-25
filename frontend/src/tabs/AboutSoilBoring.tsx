import { lang } from '../i18n'

// This page is long prose, so it is written out in both languages instead of many t() calls.
type Standard = { topic: string; topicId: string; sni: string; astm: string; astmId?: string }

const STANDARDS: Standard[] = [
  { topic: 'Standard Penetration Test (SPT)', topicId: 'Uji penetrasi standar (SPT)', sni: 'SNI 4153:2008', astm: 'ASTM D1586' },
  {
    topic: 'Cone penetration test (sondir / CPTu)',
    topicId: 'Uji penetrasi konus (sondir / CPTu)',
    sni: 'SNI 2827:2008',
    astm: 'ASTM D3441 (mechanical), ASTM D5778 (electronic)',
    astmId: 'ASTM D3441 (mekanis), ASTM D5778 (elektrik)',
  },
  { topic: 'Soil classification (USCS)', topicId: 'Klasifikasi tanah (USCS)', sni: 'SNI 6371:2015', astm: 'ASTM D2487' },
  { topic: 'Logging of core drilling', topicId: 'Pencatatan (logging) hasil bor inti', sni: 'SNI 2436:2008', astm: '-' },
]


function StandardsTable({ id }: { id: boolean }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table" style={{ minWidth: '480px' }}>
        <thead>
          <tr>
            <th>{id ? 'Topik' : 'Topic'}</th>
            <th>SNI</th>
            <th>ASTM</th>
          </tr>
        </thead>
        <tbody>
          {STANDARDS.map(s => (
            <tr key={s.topic}>
              <td>{id ? s.topicId : s.topic}</td>
              <td>{s.sni}</td>
              <td>{id ? s.astmId ?? s.astm : s.astm}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Indonesian() {
  return (
    <article className="prose">
      <h1>Mengapa Pengeboran Tanah Penting</h1>
      <p>
        Pengeboran tanah (soil boring) dan pengujian in-situ adalah gambaran pertama tentang kondisi di bawah
        permukaan sebuah lokasi. Hasilnya menentukan apakah tanah mampu memikul struktur yang direncanakan, jenis
        fondasi yang dipakai, dan risiko apa saja yang harus diperhitungkan dalam biaya sebelum konstruksi dimulai.
      </p>

      <h2>Tujuan Utama</h2>
      <ol>
        <li>
          <strong>Menentukan karakteristik tanah:</strong> jenis tanah (lempung, lanau, pasir, kerikil), konsistensi
          atau kepadatan, serta parameter kekuatan untuk daya dukung.
        </li>
        <li>
          <strong>Menilai stabilitas dan daya dukung:</strong> memastikan tanah dapat memikul struktur dengan aman
          tanpa penurunan berlebih, pergerakan lateral, atau keruntuhan.
        </li>
        <li>
          <strong>Memilih jenis fondasi:</strong> fondasi dangkal, tiang bor atau tiang pancang, termasuk kedalaman
          dan ukurannya.
        </li>
        <li>
          <strong>Mengidentifikasi risiko geoteknik:</strong> lapisan lunak atau ekspansif, muka air tanah tinggi,
          kontaminasi, atau lapisan batuan yang sulit ditembus.
        </li>
        <li>
          <strong>Mendukung perencanaan dan perhitungan biaya:</strong> metode, jadwal, dan anggaran yang realistis
          sebelum mobilisasi.
        </li>
      </ol>

      <h2>Metode Lapangan dalam Aplikasi Ini</h2>
      <ul>
        <li>
          <strong>Bor cuci (wash boring) / bor putar cuci (rotary wash) + SPT:</strong> pengeboran lubang terbuka
          dengan uji SPT pada interval tertentu; log menyimpan nilai rata-rata N60.
        </li>
        <li>
          <strong>Bor inti (coring) + SPT:</strong> pengeboran inti putar untuk tanah keras dan batuan, dengan uji SPT
          pada bagian tanah.
        </li>
        <li>
          <strong>Hollow stem auger</strong> dan <strong>bor tangan (hand auger):</strong> lubang dangkal dan
          pengambilan sampel tanpa cairan bor.
        </li>
        <li>
          <strong>CPT / CPTu (sondir):</strong> uji penetrasi konus; catat kedalaman penetrasi akhir sebagai
          kedalaman akhir.
        </li>
      </ul>

      <h2>Standar Acuan</h2>
      <p style={{ marginTop: 0 }}>
        Pekerjaan lapangan dan klasifikasi umumnya dilakukan mengacu pada Standar Nasional Indonesia (SNI) atau
        padanannya dalam ASTM:
      </p>
      <StandardsTable id />

      <h2>Manfaat Aplikasi Ini</h2>
      <ul>
        <li>
          Satu tempat untuk semua log bor: lokasi, metode pengeboran, kedalaman, muka air tanah, kelas USCS, dan
          SPT N60.
        </li>
        <li>Dasbor serta ringkasan mingguan/bulanan, dengan ringkasan opsional yang ditulis AI untuk para pemangku kepentingan proyek.</li>
        <li>Geo AI menjawab pertanyaan berdasarkan data yang tercatat dan menampilkan baris data yang dipakai sebagai bukti.</li>
        <li>
          Ekspor: CSV untuk spreadsheet, dan <strong>AGS4</strong> (satu proyek per berkas) untuk perangkat lunak
          geoteknik seperti gINT, HoleBASE, atau OpenGround.
        </li>
      </ul>
    </article>
  )
}

function English() {
  return (
    <article className="prose">
      <h1>Why Soil Boring Matters</h1>
      <p>
        Soil boring and in-situ testing are the first look at what lies under a site. The results decide
        whether the ground can carry the planned structure, which foundation to use, and which risks have to be
        priced in before construction starts.
      </p>

      <h2>Key Objectives</h2>
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

      <h2>Field Methods in This App</h2>
      <ul>
        <li><strong>Wash boring / rotary wash + SPT:</strong> open-hole drilling with SPT at set intervals; the log keeps the average N60.</li>
        <li><strong>Coring + SPT:</strong> rotary core drilling for stiff soil and rock, with SPT in the soil sections.</li>
        <li><strong>Hollow stem auger</strong> and <strong>hand auger:</strong> shallow holes and sampling without drilling fluid.</li>
        <li><strong>CPT / CPTu (sondir):</strong> cone penetration soundings; record the final penetration depth as the final depth.</li>
      </ul>

      <h2>Reference Standards</h2>
      <p style={{ marginTop: 0 }}>Field work and classification are normally carried out to the Indonesian national standard (SNI) or its ASTM counterpart:</p>
      <StandardsTable id={false} />

      <h2>How This App Helps</h2>
      <ul>
        <li>One place for every borehole log: location, drilling method, depths, groundwater, USCS class and SPT N60.</li>
        <li>Dashboards and weekly/monthly summaries, with optional AI-written briefings for project stakeholders.</li>
        <li>Geo AI answers questions from the logged data and shows the rows it used as evidence.</li>
        <li>
          Exports: CSV for spreadsheets, and <strong>AGS4</strong> (one project per file) for geotechnical software
          such as gINT, HoleBASE or OpenGround.
        </li>
      </ul>
    </article>
  )
}

export default function AboutSoilBoring() {
  return lang() === 'id' ? <Indonesian /> : <English />
}
