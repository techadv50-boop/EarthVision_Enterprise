import { HashRouter, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { Dashboard } from "./pages/Dashboard";
import { ExamRoom } from "./pages/ExamRoom";
import { Oral } from "./pages/Oral";
import { Progress } from "./pages/Progress";
import { Results } from "./pages/Results";
import { Revision } from "./pages/Revision";
import { Settings } from "./pages/Settings";
import { Study } from "./pages/Study";
import { TopicEditor } from "./pages/TopicEditor";
import { Written } from "./pages/Written";

export function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/study" element={<Study />} />
          <Route path="/study/:classId" element={<Study />} />
          <Route path="/study/:classId/:bookId" element={<Study />} />
          <Route path="/study/:classId/:bookId/:chapterId" element={<Study />} />
          <Route path="/topic/:topicId" element={<TopicEditor />} />
          <Route path="/oral/session/:sessionId" element={<Oral />} />
          <Route path="/oral" element={<Oral />} />
          <Route path="/oral/:classId" element={<Oral />} />
          <Route path="/oral/:classId/:bookId" element={<Oral />} />
          <Route path="/oral/:classId/:bookId/:chapterId" element={<Oral />} />
          <Route path="/written" element={<Written />} />
          <Route path="/written/:classId" element={<Written />} />
          <Route path="/written/:classId/:bookId" element={<Written />} />
          <Route path="/exam/:examId" element={<ExamRoom />} />
          <Route path="/exam/:examId/results" element={<Results />} />
          <Route path="/progress" element={<Progress />} />
          <Route path="/revision" element={<Revision />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
