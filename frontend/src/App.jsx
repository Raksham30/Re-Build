import { useEffect } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import Login from "./pages/Login"; import Dashboard from "./pages/Dashboard"; import Workspace from "./pages/Workspace";
import Home from "./pages/Home"; import About from "./pages/About"; import TopBar from "./components/TopBar";
function RouteScroll(){const {pathname,hash}=useLocation();useEffect(()=>{let frame=requestAnimationFrame(()=>{if(hash){const target=document.getElementById(decodeURIComponent(hash.slice(1)));if(target)target.scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"start"})}else window.scrollTo({top:0,behavior:"auto"})});return()=>cancelAnimationFrame(frame)},[pathname,hash]);return null}
export default function App() {
 const {user,loading}=useAuth(); const location=useLocation();
 if(loading)return <div className="app-shell loading-screen">Opening your research desk…</div>;
 return <div className="app-shell"><RouteScroll/><TopBar/><Routes>
  <Route path="/" element={user?<Dashboard/>:<Home/>}/>
  <Route path="/about" element={<About/>}/>
  <Route path="/login" element={user?<Navigate to={location.state?.from||"/"} replace/>:<Login/>}/>
  <Route path="/workspace/:workspaceId" element={user?<Workspace/>:<Navigate to="/login" state={{from:location}} replace/>}/>
  <Route path="*" element={<Navigate to="/" replace/>}/>
 </Routes></div>;
}
