const config_app = window.config_app;


$("#login").submit((e)=>{
    console.log(e);
    e.preventDefault();
    fetch(
        config_app.api_base+"/auth/login", {
            method: "POST",
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              "email": $("#email").val(),
              "password": $("#password").val()
            })
        }
    ).then(resp=>{
        if (resp.status == 401){
            $form = $("#form-container");
            $form.addClass('is-invalid-shake');
            // On retire la classe après l'animation (500ms) pour pouvoir la rejouer plus tard
            setTimeout(function() {
                $form.removeClass('is-invalid-shake');
            }, 500);
            throw "error"
        }
        return resp.json();
    }).then(d=>{
        if (d.token){
            localStorage.setItem("access_token", d.token);
            localStorage.setItem("role", d.role);
            if (window.socket){
                window.socket.auth.token = d.token
                //socket.disconnect().connect()
            }
            location.href = "/Administration"
        }

    })
})


$(document).ready(()=>{
    if (localStorage.getItem("access_token")){
        location.href = "/Administration";
    }

});