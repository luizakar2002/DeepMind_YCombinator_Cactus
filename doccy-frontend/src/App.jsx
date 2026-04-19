import { Routes, Route, Navigate } from "react-router-dom";
import PatientSelect from "./pages/PatientSelect";
import Session from "./pages/Session";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<PatientSelect />} />
      <Route path="/session" element={<Session />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
