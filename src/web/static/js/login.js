const config_app = window.config_app;



$("#login").submit((e)=>{
    console.log(e);
    e.preventDefault();
    fetch(
        config_app.api_base+"/login", {
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
        console.log(resp)
        return resp.json();
    }).then(d=>{
        console.log(d);
    })
})


$(document).ready(()=>{


});