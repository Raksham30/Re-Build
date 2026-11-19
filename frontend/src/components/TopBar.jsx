import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
export default function TopBar() {
 const {user,signOut}=useAuth(); const location=useLocation(); const name=user?.displayName||user?.email||"";
 const onWorkspace=location.pathname.startsWith("/workspace/"); const workspaceHref=user?"/":"/login";
 return <header className={"site-header"+(user?" site-header--app":"")}>
  <Link to="/" className="site-brand" aria-label="Research Paper Assistant home"><span className="brand-mark" aria-hidden="true">R</span><span className="brand-name">Research Paper<br/>Assistant</span></Link>
  <nav className="site-nav" aria-label="Main navigation">
   <NavLink to="/" end className={({isActive})=>"nav-link"+(isActive&&!onWorkspace?" is-active":"")}>{user?"Library":"Home"}</NavLink>
   <NavLink to={workspaceHref} className={({isActive})=>"nav-link"+(onWorkspace?" is-active":"")}>Research workspace</NavLink>
   <NavLink to="/about" className={({isActive})=>"nav-link"+(isActive?" is-active":"")}>About</NavLink>
  </nav>
  <div className="site-account">{user?<>{name&&<span className="site-user">{name}</span>}<button className="nav-cta nav-cta--quiet" onClick={signOut}>Sign out</button></>:<Link className={"nav-cta"+(location.pathname==="/login"?" nav-cta--quiet":"")} to="/login">{location.pathname==="/login"?"Sign in":"Get started"}</Link>}</div>
 </header>;
}
