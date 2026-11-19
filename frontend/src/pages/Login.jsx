import { useState } from "react";
import { useAuth } from "../hooks/useAuth";
import { Link, useLocation } from "react-router-dom";
export default function Login() {
  const {signInWithGoogle,signInWithEmail,signUpWithEmail}=useAuth(); const location=useLocation();
  const [mode,setMode]=useState("signin"); const [email,setEmail]=useState(""); const [password,setPassword]=useState(""); const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  async function handleGoogle(){setError("");setBusy(true);try{await signInWithGoogle()}catch(e){setError(friendlyError(e))}finally{setBusy(false)}}
  async function handleEmailSubmit(e){e.preventDefault();setError("");setBusy(true);try{if(mode==="signin")await signInWithEmail(email,password);else await signUpWithEmail(email,password)}catch(e){setError(friendlyError(e))}finally{setBusy(false)}}
  return <main className="login-page">
    <div className="login-art"><span className="login-art-kicker">A place for connected research</span><div className="login-art-pages" aria-hidden="true"><i/><i/><i/><b>↗</b></div><p>Read closely.<br/><em>Think across.</em></p><Link to="/" className="login-back">← Back to the field notes</Link></div>
    <section className="login-screen"><div className="login-card"><p className="login-mark">Research Paper Assistant</p>
      <h1>{mode==="signin"?"Welcome back to your research desk.":"Start a new line of inquiry."}</h1>
      <p className="login-copy">Keep your papers, questions, and cited writing together in one workspace.</p>
      <button className="button button--dark btn-google" onClick={handleGoogle} disabled={busy}>{busy?"Connecting…":"Continue with Google"}</button>
      <div className="login-divider"><span>or use your email</span></div>
      <form className="login-form" onSubmit={handleEmailSubmit}>
        <label>Email<input type="email" placeholder="you@example.com" value={email} onChange={e=>setEmail(e.target.value)} required/></label>
        <label>Password<input type="password" placeholder="At least 6 characters" value={password} onChange={e=>setPassword(e.target.value)} minLength={6} required/></label>
        <button className="button button--paper" type="submit" disabled={busy}>{busy?"Please wait…":mode==="signin"?"Sign in":"Create account"}</button>
      </form>
      <button className="login-toggle-mode" onClick={()=>{setMode(m=>m==="signin"?"signup":"signin");setError("")}}>{mode==="signin"?"New here? Create an account":"Already have an account? Sign in"}</button>
      {error&&<p className="error-text" role="alert">{error}</p>}{location.state?.from&&<p className="login-hint">Sign in to return to your workspace.</p>}
    </div></section>
  </main>;
}
function friendlyError(e){const code=e?.code||"";if(code.includes("wrong-password")||code.includes("invalid-credential"))return"Incorrect email or password.";if(code.includes("email-already-in-use"))return"That email is already registered — try signing in instead.";if(code.includes("weak-password"))return"Password should be at least 6 characters.";if(code.includes("popup-closed-by-user"))return"";return e?.message||"Something went wrong signing in."}
