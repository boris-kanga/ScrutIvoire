const config_app = window.config_app;


$(document).ready(()=>{
    fetch(
        config_app.api_base+"/election/current", {
            method: "GET",
        }
    ).then(resp=>{
        if (resp.status == 401){
            location.href = "/Administration/Connexion"
        }
        return resp.json();
    }).then(d=>{
        console.log(d, d.current);
        $("#loading-state").hide();
        if (d.current == null){
            $("#empty-state").show();
            $("#election-state").hide();
        }else{
            if (d.current.status === "OPEN"){
                $("#empty-state").hide();
                $("#election-state").show();
            }else{
                location.href = "/Administration/Archives?new="+d.current.id;
            }

        }

    })
})